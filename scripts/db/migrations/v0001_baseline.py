"""Migration v1: converge every supported legacy database to the current schema.

This is intentionally the only compatibility/probing migration.  After it is
recorded, every schema change must be a new, ordered migration.
"""
from __future__ import annotations

import asyncio
import json
import random
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Sequence

import aiosqlite

from .runner import migration_file_checksum

VERSION = 1
NAME = "baseline_current_schema"
CHECKSUM = migration_file_checksum(__file__)


@dataclass(frozen=True, slots=True)
class BaselineContext:
    get_db: Callable[..., Any]
    fetchall: Callable[..., Awaitable[list[aiosqlite.Row]]]
    fetchone: Callable[..., Awaitable[aiosqlite.Row | None]]
    data_dir: Path
    db_path: Path
    default_space: str
    space_tables: Sequence[str]


async def upgrade(ctx: BaselineContext, max_retries: int = 8) -> None:
    """执行无版本旧库的幂等结构归一化。

    1. 用 CREATE TABLE IF NOT EXISTS 保证表结构存在（与既有 DDL 完全一致）。
    2. 为 SPACE_TABLES 中的用户表统一补 `space_id` 列 + 索引（新库 / 老库走同一路径）。
       WHERE 过滤 + 索引保证任意空间查询都是单列过滤，无需 JOIN。

    多 worker 并发启动（uvicorn --workers N）时，多个进程会同时跑整套迁移；
    整个 init 是一个长写事务，必然撞锁。这里对 "database is locked" / "busy"
    类错误做指数退避 + 随机抖动重试（错开各 worker），其它错误直接抛出。
    """
    last_err: Optional[Exception] = None
    for attempt in range(max(1, max_retries)):
        try:
            await _init_db_once(ctx)
            return
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if "locked" not in msg and "busy" not in msg:
                raise
            last_err = e
            # 指数退避 + 抖动：基址 0.3s，每轮翻倍，抖动错开各 worker 的重试节拍
            delay = 0.3 * (2 ** attempt) + random.uniform(0, 0.3 * (attempt + 1))
            print(f"[db] init locked (attempt {attempt + 1}/{max_retries}), retry in {delay:.1f}s: {e}")
            await asyncio.sleep(delay)
    assert last_err is not None
    raise last_err


async def _init_db_once(ctx: BaselineContext) -> None:
    """单次 init 事务体（见 init_db 的重试说明）。"""
    async with ctx.get_db(busy_timeout_ms=30000) as conn:
        # ---------------- 论文表 ----------------
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS papers (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                authors TEXT NOT NULL,  -- JSON 数组
                abstract TEXT NOT NULL,
                arxiv_id TEXT NOT NULL,
                pdf_url TEXT NOT NULL,
                categories TEXT,  -- JSON 数组
                published_date TEXT NOT NULL,
                local_path TEXT,
                summary TEXT,
                bibtex TEXT,  -- 生成的 BibTeX 引用
                tags TEXT,  -- JSON 数组
                is_read INTEGER DEFAULT 0,
                is_favorite INTEGER DEFAULT 0,
                added_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                space_id TEXT NOT NULL DEFAULT '__default__'
            )
        ''')

        # ---------------- Cron 任务表 ----------------
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS cron_jobs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                schedule TEXT NOT NULL,
                command TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                last_run INTEGER,
                next_run INTEGER,
                run_count INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL
            )
        ''')

        # ---------------- Cron 执行历史表 ----------------
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS cron_run_history (
                id TEXT PRIMARY KEY,
                cron_job_id TEXT NOT NULL,
                space_id TEXT NOT NULL,
                status TEXT NOT NULL,
                output TEXT,
                started_at INTEGER NOT NULL,
                finished_at INTEGER,
                duration_ms INTEGER
            )
        ''')
        await conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_cron_run_history_space '
            'ON cron_run_history(space_id)')
        await conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_cron_run_history_job '
            'ON cron_run_history(cron_job_id, space_id)')

        # ---------------- 软件项目表 ----------------
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS software_projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                idea_description TEXT,  -- 原始想法描述
                tech_stack TEXT,  -- JSON 数组
                status TEXT DEFAULT 'design',  -- design, developing, testing, deployed, archived
                local_path TEXT,
                github_url TEXT,
                architecture TEXT,  -- JSON 架构设计
                features TEXT,  -- JSON 功能列表
                milestones TEXT,  -- JSON 里程碑
                ai_generated_code INTEGER DEFAULT 0,  -- 是否使用 AI 生成代码
                development_config TEXT,  -- JSON: 研发运行时、验证命令与忽略路径
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        ''')

        # ---------------- 任务表 ----------------
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'todo',  -- todo, in_progress, done, archived
                priority TEXT DEFAULT 'medium',  -- low, medium, high, urgent
                deadline INTEGER,  -- 截止时间戳
                tags TEXT,  -- JSON 数组
                project_id TEXT,  -- 关联的项目ID
                parent_task_id TEXT,  -- 父任务ID（支持子任务）
                ai_suggested INTEGER DEFAULT 0,  -- 是否 AI 建议的任务
                completed_at INTEGER,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                FOREIGN KEY (project_id) REFERENCES software_projects(id) ON DELETE SET NULL
            )
        ''')

        # ---------------- 代码生成历史表 ----------------
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS code_generations (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                prompt TEXT NOT NULL,
                generated_code TEXT NOT NULL,
                file_path TEXT,
                language TEXT,
                status TEXT DEFAULT 'pending',  -- pending, applied, rejected
                created_at INTEGER NOT NULL,
                FOREIGN KEY (project_id) REFERENCES software_projects(id) ON DELETE CASCADE
            )
        ''')

        # ---------------- 知识笔记表 ----------------
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS notes (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                summary TEXT,
                type TEXT DEFAULT 'note',  -- note, idea, summary, code_snippet
                tags TEXT,  -- JSON 数组
                paper_id TEXT,  -- 关联的论文ID
                project_id TEXT,  -- 关联的项目ID
                parent_note_id TEXT,  -- 父笔记ID（支持嵌套）
                is_favorite INTEGER DEFAULT 0,
                ai_generated INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE SET NULL,
                FOREIGN KEY (project_id) REFERENCES software_projects(id) ON DELETE SET NULL
            )
        ''')

        # ---------------- 笔记链接表 ----------------
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS note_links (
                source_note_id TEXT NOT NULL,
                target_note_id TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (source_note_id, target_note_id),
                FOREIGN KEY (source_note_id) REFERENCES notes(id) ON DELETE CASCADE,
                FOREIGN KEY (target_note_id) REFERENCES notes(id) ON DELETE CASCADE
            )
        ''')

        # ---------------- 实验表 ----------------
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS experiments (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                project_id TEXT,  -- 关联的项目
                status TEXT DEFAULT 'planning',  -- planning, running, completed, failed
                config TEXT,  -- JSON 配置参数
                tags TEXT,  -- JSON 数组
                swanlab_project TEXT,  -- SwanLab 项目名称
                swanlab_experiment_id TEXT,  -- SwanLab 实验ID
                total_runs INTEGER DEFAULT 0,
                best_metric_name TEXT,
                best_metric_value REAL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                FOREIGN KEY (project_id) REFERENCES software_projects(id) ON DELETE SET NULL
            )
        ''')

        # ---------------- 实验运行记录表 ----------------
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS experiment_runs (
                id TEXT PRIMARY KEY,
                experiment_id TEXT NOT NULL,
                run_number INTEGER NOT NULL,
                status TEXT DEFAULT 'running',  -- running, completed, failed, aborted
                config TEXT,  -- JSON 运行配置
                metrics TEXT,  -- JSON 指标数据
                swanlab_run_id TEXT,  -- SwanLab 运行ID
                started_at INTEGER NOT NULL,
                ended_at INTEGER,
                duration INTEGER,  -- 运行时长（秒）
                FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE
            )
        ''')

        # ---------------- 索引 ----------------
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_papers_arxiv ON papers(arxiv_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_papers_added ON papers(added_at DESC)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_papers_read ON papers(is_read)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_papers_favorite ON papers(is_favorite)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_papers_title ON papers(title)')

        await conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_deadline ON tasks(deadline)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_task_id)')

        await conn.execute('CREATE INDEX IF NOT EXISTS idx_projects_status ON software_projects(status)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_code_gen_project ON code_generations(project_id)')

        await conn.execute('CREATE INDEX IF NOT EXISTS idx_notes_type ON notes(type)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_notes_favorite ON notes(is_favorite)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_notes_paper ON notes(paper_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_notes_project ON notes(project_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_notes_parent ON notes(parent_note_id)')

        await conn.execute('CREATE INDEX IF NOT EXISTS idx_experiments_status ON experiments(status)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_experiments_project ON experiments(project_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_experiment_runs_experiment ON experiment_runs(experiment_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_experiment_runs_swanlab ON experiment_runs(swanlab_run_id)')

        # ---------------- 版本历史表 ----------------
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS version_history (
                id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,  -- 'note', 'task', 'project', etc.
                entity_id TEXT NOT NULL,    -- 实体的ID
                version_number INTEGER NOT NULL,
                data TEXT NOT NULL,         -- JSON格式的完整数据
                change_summary TEXT,        -- 变更摘要
                created_by TEXT,            -- 创建者（如果是AI操作）
                created_at INTEGER NOT NULL,
                FOREIGN KEY (entity_id) REFERENCES notes(id) ON DELETE CASCADE
            )
        ''')

        await conn.execute('CREATE INDEX IF NOT EXISTS idx_version_entity ON version_history(entity_type, entity_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_version_number ON version_history(entity_id, version_number DESC)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_version_created ON version_history(created_at DESC)')

        # ---------------- 对话会话表 ----------------
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '新对话',
                current_leaf_id TEXT,  -- 当前分支的最新消息 id（支持分叉树）
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                metadata TEXT,  -- JSON：会话级配置（如 RAG 接地开关 / 来源筛选），按会话持久化
                FOREIGN KEY (current_leaf_id) REFERENCES chat_messages(id) ON DELETE SET NULL
            )
        ''')

        # ---------------- 聊天消息表 ----------------
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS chat_messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                parent_id TEXT,  -- 父消息 id，同一会话内构成分叉树
                role TEXT NOT NULL,  -- 'user', 'assistant', 'system'
                content TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                metadata TEXT,  -- JSON 格式，存储额外信息
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
                FOREIGN KEY (parent_id) REFERENCES chat_messages(id) ON DELETE CASCADE
            )
        ''')

        await conn.execute('CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at DESC)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation ON chat_messages(conversation_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_chat_messages_timestamp ON chat_messages(timestamp)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_chat_messages_conv_parent ON chat_messages(conversation_id, parent_id)')

        # ---------------- Agent 会话表 ----------------
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS agent_sessions (
                id TEXT PRIMARY KEY,
                project_id TEXT,  -- 关联的软件项目
                session_type TEXT NOT NULL,  -- 'architect', 'planner', 'developer'
                status TEXT DEFAULT 'running',  -- 'running', 'completed', 'failed'
                input_data TEXT NOT NULL,  -- JSON: 输入参数
                output_data TEXT,  -- JSON: 输出结果
                progress INTEGER DEFAULT 0,  -- 进度 0-100
                current_step TEXT,  -- 当前执行的步骤
                started_at INTEGER NOT NULL,
                completed_at INTEGER,
                error_message TEXT,
                FOREIGN KEY (project_id) REFERENCES software_projects(id) ON DELETE CASCADE
            )
        ''')

        # ---------------- Agent 消息/思考记录表 ----------------
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS agent_messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                agent_role TEXT NOT NULL,  -- 'architect', 'planner', 'developer', 'reviewer'
                message_type TEXT NOT NULL,  -- 'thinking', 'action', 'output', 'error'
                content TEXT NOT NULL,
                step_name TEXT,  -- 所属步骤
                metadata TEXT,  -- JSON: 额外信息
                timestamp INTEGER NOT NULL,
                FOREIGN KEY (session_id) REFERENCES agent_sessions(id) ON DELETE CASCADE
            )
        ''')

        # ---------------- Agent 生成的文件表 ----------------
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS agent_generated_files (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                file_path TEXT NOT NULL,
                content TEXT NOT NULL,
                file_type TEXT,  -- 'code', 'config', 'doc', 'test'
                description TEXT,
                created_at INTEGER NOT NULL,
                FOREIGN KEY (session_id) REFERENCES agent_sessions(id) ON DELETE CASCADE
            )
        ''')

        # ---------------- Agent 后台运行记录表（非阻塞 runner） ----------------
        # 一次「多 Agent 协作」提交即一条 run；状态机 pending/running/completed/failed/cancelled。
        # 事件流（每个角色产出的 phase_start/start/complete/error...）落 agent_run_events，
        # 由后台线程按事件持久化，前端可轮询或 SSE 订阅，天然跨多 worker 可见。
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS agent_runs (
                id TEXT PRIMARY KEY,
                space_id TEXT NOT NULL,
                project_id TEXT,
                requirement TEXT NOT NULL,
                roles TEXT NOT NULL,  -- JSON: 本次实际执行的角色 key 列表
                status TEXT NOT NULL DEFAULT 'running',  -- pending/running/completed/failed/cancelled
                error_message TEXT,
                result_summary TEXT,  -- JSON: 各角色结构化产物
                created_at INTEGER NOT NULL,
                started_at INTEGER,
                completed_at INTEGER,
                team_id TEXT,
                team_name TEXT,
                team_snapshot TEXT,
                input_context TEXT
            )
        ''')

        # ---------------- 持久化研发工作区 ----------------
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS development_run_steps (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                space_id TEXT NOT NULL,
                iteration INTEGER NOT NULL,
                phase TEXT NOT NULL,
                stage_node_id TEXT,
                attempt INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'pending',
                input_summary TEXT,
                output TEXT,
                error_message TEXT,
                started_at INTEGER,
                completed_at INTEGER,
                UNIQUE(run_id, iteration, phase, attempt)
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS development_artifacts (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                space_id TEXT NOT NULL,
                iteration INTEGER NOT NULL DEFAULT 0,
                kind TEXT NOT NULL,
                relative_path TEXT,
                content TEXT,
                metadata TEXT,
                created_at INTEGER NOT NULL
            )
        ''')
        await conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_development_steps_run '
            'ON development_run_steps(run_id, space_id, iteration)')
        await conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_development_artifacts_run '
            'ON development_artifacts(run_id, space_id, iteration)')

        # User-authored definitions are space-private. Built-in teams and role
        # templates remain version-controlled JSON and are not inserted here.
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS agent_teams (
                id TEXT PRIMARY KEY,
                space_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                category TEXT,
                definition TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS agent_role_templates (
                id TEXT PRIMARY KEY,
                space_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                definition TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS agent_run_nodes (
                run_id TEXT NOT NULL,
                node_id TEXT NOT NULL,
                space_id TEXT NOT NULL,
                node_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                text_output TEXT,
                structured_output TEXT,
                error_message TEXT,
                queued_at INTEGER,
                started_at INTEGER,
                completed_at INTEGER,
                PRIMARY KEY (run_id, node_id)
            )
        ''')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_agent_teams_space ON agent_teams(space_id, updated_at DESC)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_agent_role_templates_space ON agent_role_templates(space_id, updated_at DESC)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_agent_run_nodes_run ON agent_run_nodes(run_id, space_id)')

        # ---------------- Agent 运行事件流表 ----------------
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS agent_run_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                space_id TEXT NOT NULL,
                type TEXT NOT NULL,  -- phase_start/start/complete/error/run_complete/run_cancelled...
                data TEXT NOT NULL,  -- JSON: 事件原文（与 SSE 事件同构）
                created_at INTEGER NOT NULL
            )
        ''')

        await conn.execute('CREATE INDEX IF NOT EXISTS idx_agent_runs_space ON agent_runs(space_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_agent_runs_project ON agent_runs(project_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_agent_runs_status ON agent_runs(status)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_agent_run_events_run ON agent_run_events(run_id, id)')

        # ---------------- Agent 工具审批表（P0：工具审批） ----------------
        # 每次「需要审批的工具调用」落一行，状态机 pending -> approved/denied/timed_out/cancelled。
        # 后台 runner 线程轮询该表等待用户决策（跨 worker 可见，与 agent_runs 同一哲学）。
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS agent_tool_approvals (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                space_id TEXT NOT NULL,
                tool TEXT NOT NULL,
                node_id TEXT,
                parameters TEXT NOT NULL,  -- JSON: 本次调用参数
                status TEXT NOT NULL DEFAULT 'pending',
                created_at INTEGER NOT NULL,
                decided_at INTEGER
            )
        ''')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_agent_approvals_run ON agent_tool_approvals(run_id, status)')

        # ---------------- Agent 可重放消息表（P1：可重放会话日志） ----------------
        # 逐轮落库「模型实际看到的消息序列」（system/user/assistant含tool_calls/tool），
        # 实现"Model-visible ⟺ logged"：出问题可按 run_id 完整重放定位。
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS agent_replay_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                space_id TEXT NOT NULL,
                phase TEXT NOT NULL,      -- 角色 key（architect/planner/...）
                round INTEGER NOT NULL DEFAULT 0,  -- 0=初始消息，1..n=工具反思轮
                role TEXT NOT NULL,       -- system/user/assistant/tool
                content TEXT NOT NULL,    -- JSON: 单条消息（含 tool_calls 时保留结构）
                created_at INTEGER NOT NULL
            )
        ''')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_agent_replay_run ON agent_replay_messages(run_id, id)')

        # ---------------- Formula 识别历史表 ----------------
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS formula_history (
                id TEXT PRIMARY KEY,
                image_data TEXT,  -- Base64 编码的图片（可选存储）
                latex_code TEXT NOT NULL,
                confidence REAL DEFAULT 0,
                source_type TEXT DEFAULT 'upload',  -- upload/paste/screenshot
                is_favorite INTEGER DEFAULT 0,
                tags TEXT,  -- JSON 数组
                note TEXT,
                created_at INTEGER NOT NULL
            )
        ''')

        await conn.execute('CREATE INDEX IF NOT EXISTS idx_formula_favorite ON formula_history(is_favorite)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_formula_created ON formula_history(created_at DESC)')

        await conn.execute('CREATE INDEX IF NOT EXISTS idx_agent_sessions_project ON agent_sessions(project_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_agent_sessions_status ON agent_sessions(status)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_agent_messages_session ON agent_messages(session_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_agent_messages_timestamp ON agent_messages(timestamp)')

        # ---------------- Obsidian Vault 表 ----------------
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS obsidian_vaults (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                vault_path TEXT NOT NULL,
                sync_mode TEXT DEFAULT 'manual',
                last_sync_at INTEGER,
                is_active BOOLEAN DEFAULT 1,
                created_at INTEGER DEFAULT (strftime('%s', 'now')),
                updated_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
        ''')

        # ---------------- Obsidian 文件表 ----------------
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS obsidian_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vault_id INTEGER,
                relative_path TEXT NOT NULL,
                file_hash TEXT,
                modified_time INTEGER,
                content_preview TEXT,
                frontmatter TEXT,
                tags TEXT,
                links TEXT,
                backlinks TEXT,
                sync_status TEXT DEFAULT 'pending',
                last_sync_at INTEGER,
                FOREIGN KEY (vault_id) REFERENCES obsidian_vaults(id)
            )
        ''')

        await conn.execute('CREATE INDEX IF NOT EXISTS idx_obsidian_files_vault ON obsidian_files(vault_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_obsidian_files_path ON obsidian_files(relative_path)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_obsidian_files_status ON obsidian_files(sync_status)')

        # ---------------- RAG 检索表（向量库） ----------------
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS rag_sources (
                id TEXT NOT NULL,
                space_id TEXT NOT NULL DEFAULT '__default__',
                name TEXT,
                kind TEXT DEFAULT 'local',    -- local|paper|web：本地路径 / 论文库系统源 / 网页粘贴
                target_paths TEXT,            -- JSON 数组：一个或多个目标路径（paper/web 源可为空）
                recursive INTEGER DEFAULT 1,  -- 是否递归子目录
                file_types TEXT,             -- JSON 数组：如 ["pdf","txt","md"]
                status TEXT DEFAULT 'pending',   -- pending|indexing|ready|partial|failed|cancelled
                doc_count INTEGER DEFAULT 0,
                chunk_count INTEGER DEFAULT 0,
                progress INTEGER DEFAULT 0,   -- 索引进度 0-100（indexing 时实时更新）
                total_files INTEGER DEFAULT 0, -- 本次索引发现的文件总数
                embedding_model TEXT,
                embedding_provider TEXT,
                embedding_revision TEXT,
                embedding_dims INTEGER DEFAULT 0,
                embedding_profile_id TEXT,
                active_generation_id TEXT,
                embed_mode TEXT DEFAULT 'keyword',  -- vector|keyword
                error TEXT,
                created_at INTEGER,
                updated_at INTEGER,
                PRIMARY KEY (space_id, id)
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS rag_documents (
                id TEXT NOT NULL,
                space_id TEXT NOT NULL DEFAULT '__default__',
                source_id TEXT,
                file_path TEXT,
                file_name TEXT,
                file_type TEXT,
                file_size INTEGER,
                page_count INTEGER,
                char_count INTEGER,
                chunk_count INTEGER,
                url TEXT,                     -- web 文档规范化 URL；paper 为 arXiv 链接；local 为空
                title TEXT,                   -- 文档标题（网页 <title> / 论文标题 / 文件名回退）
                section TEXT,                 -- 切分用节名（论文 abstract/章节；网页为标题回退）
                content_hash TEXT,            -- 全文 sha1，用于增量去重
                fetched_at INTEGER,           -- web 抓取时间戳（ms）；其它为空
                generation_id TEXT,
                created_at INTEGER,
                PRIMARY KEY (space_id, id)
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS rag_chunks (
                id TEXT NOT NULL,
                space_id TEXT NOT NULL DEFAULT '__default__',
                source_id TEXT,
                doc_id TEXT,
                chunk_index INTEGER,
                content TEXT,
                page_start INTEGER,
                page_end INTEGER,
                char_start INTEGER,
                char_end INTEGER,
                embedding TEXT,             -- JSON 数组浮点；关键词模式下为 NULL
                embedding_profile_id TEXT,
                generation_id TEXT,
                token_count INTEGER,
                created_at INTEGER,
                PRIMARY KEY (space_id, id)
            )
        ''')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_rag_sources_space ON rag_sources(space_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_rag_sources_status ON rag_sources(space_id, status)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_rag_documents_space ON rag_documents(space_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_rag_documents_source ON rag_documents(space_id, source_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_rag_chunks_space ON rag_chunks(space_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_rag_chunks_source ON rag_chunks(space_id, source_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_rag_chunks_doc ON rag_chunks(space_id, doc_id)')

        # 嵌入空间是索引正确性的边界：provider/model/revision/dims 任一变化都不得混检。
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS rag_embedding_profiles (
                id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                revision TEXT,
                dims INTEGER NOT NULL,
                normalized INTEGER NOT NULL DEFAULT 1,
                query_instruction TEXT,
                created_at INTEGER
            )
        ''')
        # 2.0 早期版本误把 source id 设为全局主键，导致不同 space 的
        # __papers__/__web__ 冲突。老库原地重建为 (space_id, id) 复合主键。
        _src_info = await (await conn.execute("PRAGMA table_info(rag_sources)")).fetchall()
        _src_pk = [r["name"] for r in sorted(_src_info, key=lambda r: r["pk"]) if r["pk"]]
        if _src_pk == ["id"]:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS rag_sources_v21 (
                    id TEXT NOT NULL, space_id TEXT NOT NULL DEFAULT '__default__',
                    name TEXT, kind TEXT DEFAULT 'local', target_paths TEXT,
                    recursive INTEGER DEFAULT 1, file_types TEXT, status TEXT DEFAULT 'pending',
                    doc_count INTEGER DEFAULT 0, chunk_count INTEGER DEFAULT 0,
                    progress INTEGER DEFAULT 0, total_files INTEGER DEFAULT 0,
                    embedding_model TEXT, embedding_provider TEXT, embedding_revision TEXT,
                    embedding_dims INTEGER DEFAULT 0, embedding_profile_id TEXT,
                    active_generation_id TEXT, embed_mode TEXT DEFAULT 'keyword', error TEXT,
                    created_at INTEGER, updated_at INTEGER, PRIMARY KEY (space_id, id)
                )
            ''')
            _old_names = {r["name"] for r in _src_info}
            _new_info = await (await conn.execute("PRAGMA table_info(rag_sources_v21)")).fetchall()
            _common = [r["name"] for r in _new_info if r["name"] in _old_names]
            _columns = ", ".join(_common)
            await conn.execute(
                f"INSERT OR IGNORE INTO rag_sources_v21 ({_columns}) SELECT {_columns} FROM rag_sources")
            await conn.execute("DROP TABLE rag_sources")
            await conn.execute("ALTER TABLE rag_sources_v21 RENAME TO rag_sources")
        # documents/chunks 同样按空间确定身份；旧表无 FK，重建不会破坏关联。
        for _table, _ddl in [
            ("rag_documents", '''CREATE TABLE rag_documents_v21 (
                id TEXT NOT NULL, space_id TEXT NOT NULL DEFAULT '__default__', source_id TEXT,
                file_path TEXT, file_name TEXT, file_type TEXT, file_size INTEGER,
                page_count INTEGER, char_count INTEGER, chunk_count INTEGER, url TEXT,
                title TEXT, section TEXT, content_hash TEXT, fetched_at INTEGER,
                generation_id TEXT, created_at INTEGER, PRIMARY KEY (space_id, id))'''),
            ("rag_chunks", '''CREATE TABLE rag_chunks_v21 (
                id TEXT NOT NULL, space_id TEXT NOT NULL DEFAULT '__default__', source_id TEXT,
                doc_id TEXT, chunk_index INTEGER, content TEXT, page_start INTEGER,
                page_end INTEGER, char_start INTEGER, char_end INTEGER, embedding TEXT,
                embedding_profile_id TEXT, generation_id TEXT, token_count INTEGER,
                created_at INTEGER, PRIMARY KEY (space_id, id))'''),
        ]:
            _info = await (await conn.execute(f"PRAGMA table_info({_table})")).fetchall()
            _pk = [r["name"] for r in sorted(_info, key=lambda r: r["pk"]) if r["pk"]]
            if _pk == ["id"]:
                _new = _table + "_v21"
                await conn.execute(f"DROP TABLE IF EXISTS {_new}")
                await conn.execute(_ddl)
                _old_names = {r["name"] for r in _info}
                _new_info = await (await conn.execute(f"PRAGMA table_info({_new})")).fetchall()
                _common = [r["name"] for r in _new_info if r["name"] in _old_names]
                _columns = ", ".join(_common)
                await conn.execute(
                    f"INSERT OR IGNORE INTO {_new} ({_columns}) SELECT {_columns} FROM {_table}")
                await conn.execute(f"DROP TABLE {_table}")
                await conn.execute(f"ALTER TABLE {_new} RENAME TO {_table}")

        # ---------------- RAG 索引任务队列（P1 单写者：重型索引写操作串行化） ----------------
        # 背景：8 worker 人人直写同一 SQLite，重型索引事务（万级切片）必然撞锁。
        # 所有 local 索引提交先入队，各 worker 用 claim 原子认领，全局同时只有一个
        # 执行者；认领走单条 UPDATE...RETURNING，保证跨进程互斥。
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS rag_index_jobs (
                id TEXT PRIMARY KEY,
                space_id TEXT NOT NULL DEFAULT '__default__',
                kind TEXT DEFAULT 'local_index', -- local_index：本地路径索引
                source_id TEXT,                 -- 关联 rag_sources.id（去重/取消用）
                dedupe_key TEXT,
                payload TEXT,                   -- JSON：{paths, recursive, file_types}
                status TEXT DEFAULT 'pending',  -- pending|claimed|running|done|failed|cancelled
                claimer TEXT,                   -- 认领者 worker 标识
                lease_expires_at INTEGER,       -- 租约到期（ms）；过期可被重认领
                error TEXT,
                created_at INTEGER,
                updated_at INTEGER
            )
        ''')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_rag_jobs_status ON rag_index_jobs(status, created_at)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_rag_jobs_source ON rag_index_jobs(space_id, source_id, status)')

        # 全进程/多 worker 共享的单写者租约。job 自身的 lease 只负责故障接管，
        # 不能阻止两个 dispatcher 同时领取两个不同任务。
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS rag_worker_lease (
                name TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        ''')

        # ---------------- RAG 向量存储元信息（P2 sqlite-vec） ----------------
        # vec0 虚表由 vec_store 懒创建（维度取自首批向量）；这里只存固定 schema 的
        # 元信息：dims（建表维度）、ready（表内数据是否与主表同步）。
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS rag_vec_meta (
                space_id TEXT PRIMARY KEY,
                dims INTEGER DEFAULT 0,
                profile_id TEXT,
                ready INTEGER DEFAULT 0,
                updated_at INTEGER
            )
        ''')

        # ---- RAG P0 幂等补列（老库升级；必须在 kind/hash/url 索引之前）----
        for _tbl, _col, _decl in [
            ("rag_sources", "kind", "TEXT DEFAULT 'local'"),
            ("rag_sources", "progress", "INTEGER DEFAULT 0"),
            ("rag_sources", "total_files", "INTEGER DEFAULT 0"),
            ("rag_documents", "url", "TEXT"),
            ("rag_documents", "title", "TEXT"),
            ("rag_documents", "section", "TEXT"),
            ("rag_documents", "content_hash", "TEXT"),
            ("rag_documents", "fetched_at", "INTEGER"),
        ]:
            try:
                _cols = await (await conn.execute(f"PRAGMA table_info({_tbl})")).fetchall()
                if _col not in {r["name"] for r in _cols}:
                    await conn.execute(f"ALTER TABLE {_tbl} ADD COLUMN {_col} {_decl}")
            except sqlite3.OperationalError as _e:
                if "duplicate column" not in str(_e).lower():
                    raise
        # 存量 local 源补 kind
        try:
            await conn.execute("UPDATE rag_sources SET kind = 'local' WHERE kind IS NULL OR kind = ''")
        except Exception:
            pass
        # 新列索引（补列之后建，老库不再报 no such column）
        for _idx_sql in [
            'CREATE INDEX IF NOT EXISTS idx_rag_sources_kind ON rag_sources(space_id, kind)',
            'CREATE INDEX IF NOT EXISTS idx_rag_docs_hash ON rag_documents(space_id, content_hash)',
            'CREATE INDEX IF NOT EXISTS idx_rag_docs_url ON rag_documents(space_id, url)',
        ]:
            try:
                await conn.execute(_idx_sql)
            except sqlite3.OperationalError:
                pass

        # ---- RAG FTS5（BM25 稀疏索引，SQLite 内置；不可用则检索侧回退 LIKE/词频）----
        # 2026-09-09 返工：逐行触发器在万级删除下是灾难——chunk_id 列 UNINDEXED，
        # 每次 DELETE 都触发一次全表扫描（5 万行表 × 2.5 万次删除），且全程持写锁，
        # 直接导致 reindex/删源在多 worker 下 database is locked。
        # 改为显式集合维护（insert_rag_chunks / clear_rag_chunks / delete_rag_document
        # 内批量同步 FTS，无触发器）：批量写是集合操作，无逐行扫描。
        try:
            await conn.execute('''
                CREATE VIRTUAL TABLE IF NOT EXISTS rag_chunks_fts
                USING fts5(content, chunk_id UNINDEXED, space_id UNINDEXED, tokenize = "trigram")
            ''')
            await conn.execute('DROP TRIGGER IF EXISTS trg_rag_chunks_fts_ai')
            await conn.execute('DROP TRIGGER IF EXISTS trg_rag_chunks_fts_ad')
            # 存量回填（缺失补齐）+ 孤儿清理（触发器时代残留/崩溃中间态）。
            # 先比行数：稳态下两次 COUNT 都是索引扫描，远比全表操作便宜，
            # 避免每次启动都扫全表 rag_chunks 长时间持写锁。
            try:
                _n_chunks = await (await conn.execute("SELECT COUNT(*) AS n FROM rag_chunks")).fetchone()
                _n_fts = await (await conn.execute("SELECT COUNT(*) AS n FROM rag_chunks_fts")).fetchone()
                _nc = (_n_chunks and _n_chunks["n"]) or 0
                _nf = (_n_fts and _n_fts["n"]) or 0
                if _nc > _nf:
                    await conn.execute('''
                        INSERT INTO rag_chunks_fts(content, chunk_id, space_id)
                        SELECT c.content, c.id, c.space_id FROM rag_chunks c
                        LEFT JOIN rag_chunks_fts f
                          ON f.chunk_id = c.id AND f.space_id = c.space_id
                        WHERE f.chunk_id IS NULL
                    ''')
                elif _nf > _nc:
                    await conn.execute('''
                        DELETE FROM rag_chunks_fts
                        WHERE NOT EXISTS (
                            SELECT 1 FROM rag_chunks c
                            WHERE c.id = rag_chunks_fts.chunk_id
                              AND c.space_id = rag_chunks_fts.space_id
                        )
                    ''')
            except Exception:
                pass
        except Exception as _fts_e:  # noqa: BLE001 - 无 FTS5 的精简 sqlite 构建仍可启动
            print(f"[db] FTS5 unavailable, BM25 disabled: {_fts_e}")

        # ==================== space_id 幂等迁移 ====================
        # 新库与老库走同一路径：补列 + 建索引，存量行自动打 __default__。
        # 多 worker 并发 init 时，可能两个进程同时通过 table_info 检查并试图 ALTER，
        # 后到者会撞 "duplicate column"；此处忽略该良性冲突，视为已补列成功。
        for tbl in ctx.space_tables:
            cols = await (await conn.execute(f"PRAGMA table_info({tbl})")).fetchall()
            col_names = {r["name"] for r in cols}
            if "space_id" not in col_names:
                # NOT NULL + DEFAULT：存量行自动打 __default__；空表也安全。
                try:
                    await conn.execute(
                        f"ALTER TABLE {tbl} ADD COLUMN space_id TEXT NOT NULL DEFAULT '{ctx.default_space}'"
                    )
                except sqlite3.OperationalError as e:
                    if "duplicate column" in str(e).lower():
                        pass  # 另一 worker 已抢先补列，忽略
                    else:
                        raise
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{tbl}_space ON {tbl}(space_id)"
            )

        # Composite space-aware indexes (space_id first) for hot filtered queries.
        # 必须在 space_id 补列迁移之后建：新库建表 DDL 尚无 space_id 列，
        # 提前建会报 no such column（见 qa_verify_agent_harness 新库回归）。
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_space_project ON tasks(space_id, project_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_space_status ON tasks(space_id, status)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_notes_space_updated ON notes(space_id, updated_at DESC)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_version_space_entity ON version_history(space_id, entity_type, entity_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_conversations_space_updated ON conversations(space_id, updated_at DESC)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_chat_messages_space_conv ON chat_messages(space_id, conversation_id)')

        # Agent team migration. Each ALTER is independently idempotent so
        # concurrent uvicorn workers can initialize an old database safely.
        async def ensure_column(table: str, column: str, declaration: str) -> None:
            existing = await (await conn.execute(f"PRAGMA table_info({table})")).fetchall()
            if column in {row["name"] for row in existing}:
                return
            try:
                await conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc).lower():
                    raise

        await ensure_column("agent_runs", "team_id", "TEXT")
        await ensure_column("agent_runs", "team_name", "TEXT")
        await ensure_column("agent_runs", "team_snapshot", "TEXT")
        await ensure_column("agent_runs", "input_context", "TEXT")
        await ensure_column("agent_runs", "run_kind", "TEXT NOT NULL DEFAULT 'dag'")
        await ensure_column("agent_runs", "phase", "TEXT")
        await ensure_column("agent_runs", "iteration", "INTEGER NOT NULL DEFAULT 0")
        await ensure_column("agent_runs", "max_iterations", "INTEGER")
        await ensure_column("agent_runs", "deadline_at", "INTEGER")
        await ensure_column("agent_runs", "workspace_snapshot", "TEXT")
        await ensure_column("agent_runs", "checkpoint", "TEXT")
        await ensure_column("agent_runs", "authorization", "TEXT")
        await ensure_column("agent_runs", "lease_owner", "TEXT")
        await ensure_column("agent_runs", "lease_expires_at", "INTEGER")
        await ensure_column("agent_runs", "budget_used_ms", "INTEGER NOT NULL DEFAULT 0")
        await ensure_column("agent_tool_approvals", "node_id", "TEXT")
        await ensure_column("software_projects", "development_config", "TEXT")
        await ensure_column("rag_sources", "embedding_provider", "TEXT")
        await ensure_column("rag_sources", "embedding_revision", "TEXT")
        await ensure_column("rag_sources", "embedding_dims", "INTEGER DEFAULT 0")
        await ensure_column("rag_sources", "embedding_profile_id", "TEXT")
        await ensure_column("rag_sources", "active_generation_id", "TEXT")
        await ensure_column("rag_documents", "generation_id", "TEXT")
        await ensure_column("rag_chunks", "embedding_profile_id", "TEXT")
        await ensure_column("rag_chunks", "generation_id", "TEXT")
        await ensure_column("rag_vec_meta", "profile_id", "TEXT")
        await ensure_column("rag_index_jobs", "dedupe_key", "TEXT")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rag_docs_generation "
            "ON rag_documents(space_id, source_id, generation_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rag_chunks_generation "
            "ON rag_chunks(space_id, source_id, generation_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rag_chunks_profile "
            "ON rag_chunks(space_id, embedding_profile_id)"
        )

        # 一次性迁移：papers 表补 bibtex 列（老库无此列，幂等执行）
        cols = await (await conn.execute("PRAGMA table_info(papers)")).fetchall()
        if "bibtex" not in {r["name"] for r in cols}:
            try:
                await conn.execute("ALTER TABLE papers ADD COLUMN bibtex TEXT")
            except sqlite3.OperationalError as e:
                if "duplicate column" in str(e).lower():
                    pass  # 另一 worker 已抢先补列，忽略
                else:
                    raise

        # 旧版 papers.arxiv_id 是全局 UNIQUE，会阻止不同空间收藏同一篇论文。
        # 重建表以移除旧约束，再用 (space_id, arxiv_id) 做空间内唯一。
        await _maybe_migrate_paper_space_uniqueness(conn)

        # 幂等迁移：cron_jobs 补 job_type / payload 列（调度器扩展，兼容旧库）
        cron_cols = await (await conn.execute("PRAGMA table_info(cron_jobs)")).fetchall()
        cron_col_names = {r["name"] for r in cron_cols}
        if "job_type" not in cron_col_names:
            try:
                await conn.execute(
                    "ALTER TABLE cron_jobs ADD COLUMN job_type TEXT NOT NULL DEFAULT 'command'")
            except sqlite3.OperationalError as e:
                if "duplicate column" in str(e).lower():
                    pass
                else:
                    raise
        if "payload" not in cron_col_names:
            try:
                await conn.execute("ALTER TABLE cron_jobs ADD COLUMN payload TEXT")
            except sqlite3.OperationalError as e:
                if "duplicate column" in str(e).lower():
                    pass
                else:
                    raise

        # 一次性迁移：存量 cron_jobs.json -> DB（仅当表为空时，避免多 worker 重复导入）
        await _maybe_migrate_cron_json(conn, ctx)

        # 迁移：修正历史“用户”占位节点名（回落为 node_id，前端再映射真名）
        try:
            await conn.execute("UPDATE agent_run_nodes SET node_name = node_id WHERE node_name = '用户'")
        except Exception:
            pass

        # ==================== 全局配置表（热更新，跨 worker 可见） ====================
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS global_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            )
        ''')

        # ==================== chat 消息分叉树迁移 ====================
        # 老库只有扁平线性消息，需补 parent_id / current_leaf_id 并回填。
        await _maybe_migrate_chat_branching(conn, ctx)

    print(f"Database initialized at {ctx.db_path}")


async def _paper_has_global_arxiv_unique(conn: aiosqlite.Connection) -> bool:
    indexes = await (await conn.execute("PRAGMA index_list(papers)")).fetchall()
    for index in indexes:
        if not index["unique"]:
            continue
        name = str(index["name"]).replace('"', '""')
        columns = await (await conn.execute(f'PRAGMA index_info("{name}")')).fetchall()
        if [column["name"] for column in columns] == ["arxiv_id"]:
            return True
    return False


async def _create_paper_indexes(conn: aiosqlite.Connection) -> None:
    await conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_space_arxiv "
        "ON papers(space_id, arxiv_id)"
    )
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_papers_arxiv ON papers(arxiv_id)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_papers_added ON papers(added_at DESC)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_papers_read ON papers(is_read)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_papers_favorite ON papers(is_favorite)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_papers_title ON papers(title)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_papers_space ON papers(space_id)')


async def _maybe_migrate_paper_space_uniqueness(conn: aiosqlite.Connection) -> None:
    """Replace the legacy global arXiv uniqueness constraint without losing rows."""
    if not await _paper_has_global_arxiv_unique(conn):
        await _create_paper_indexes(conn)
        return

    # Some legacy databases may already contain unrelated orphan rows from
    # older versions that did not enable foreign_keys consistently.  The
    # papers rebuild must not introduce any *new* violation, but pre-existing
    # violations in other tables must not make the application unbootable.
    baseline_violations = {
        tuple(row) for row in
        await (await conn.execute("PRAGMA foreign_key_check")).fetchall()
    }

    # PRAGMA foreign_keys cannot be changed inside a transaction.  Commit any
    # preceding idempotent DDL, then serialize the table rebuild across workers.
    await conn.commit()
    await conn.execute("PRAGMA foreign_keys=OFF")
    try:
        await conn.execute("BEGIN IMMEDIATE")
        # Another worker may have completed the migration while this one waited.
        if not await _paper_has_global_arxiv_unique(conn):
            await _create_paper_indexes(conn)
            await conn.commit()
            return

        # Rebuilding a SQLite table drops all of its indexes. Preserve every
        # defined index except the obsolete global arXiv uniqueness index.
        index_rows = await (await conn.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type = 'index' AND tbl_name = 'papers' AND sql IS NOT NULL"
        )).fetchall()
        index_sql_to_restore: list[str] = []
        for index in index_rows:
            name = str(index["name"]).replace('"', '""')
            columns = await (await conn.execute(f'PRAGMA index_info("{name}")')).fetchall()
            if [column["name"] for column in columns] != ["arxiv_id"]:
                index_sql_to_restore.append(index["sql"])

        await conn.execute("DROP TABLE IF EXISTS papers__space_unique_new")
        await conn.execute('''
            CREATE TABLE papers__space_unique_new (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                authors TEXT NOT NULL,
                abstract TEXT NOT NULL,
                arxiv_id TEXT NOT NULL,
                pdf_url TEXT NOT NULL,
                categories TEXT,
                published_date TEXT NOT NULL,
                local_path TEXT,
                summary TEXT,
                bibtex TEXT,
                tags TEXT,
                is_read INTEGER DEFAULT 0,
                is_favorite INTEGER DEFAULT 0,
                added_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                space_id TEXT NOT NULL DEFAULT '__default__'
            )
        ''')
        await conn.execute('''
            INSERT INTO papers__space_unique_new
            (id, title, authors, abstract, arxiv_id, pdf_url, categories,
             published_date, local_path, summary, bibtex, tags, is_read,
             is_favorite, added_at, updated_at, space_id)
            SELECT id, title, authors, abstract, arxiv_id, pdf_url, categories,
                   published_date, local_path, summary, bibtex, tags, is_read,
                   is_favorite, added_at, updated_at, space_id
            FROM papers
        ''')
        await conn.execute("DROP TABLE papers")
        await conn.execute("ALTER TABLE papers__space_unique_new RENAME TO papers")
        for index_sql in index_sql_to_restore:
            await conn.execute(index_sql)
        await _create_paper_indexes(conn)

        violations = {
            tuple(row) for row in
            await (await conn.execute("PRAGMA foreign_key_check")).fetchall()
        }
        new_violations = violations - baseline_violations
        if new_violations:
            raise RuntimeError(
                f"paper uniqueness migration broke foreign keys: {sorted(new_violations)}")
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise
    finally:
        await conn.execute("PRAGMA foreign_keys=ON")


async def _maybe_migrate_cron_json(conn: aiosqlite.Connection, ctx: BaselineContext) -> None:
    """将遗留的 cron_jobs.json 一次性迁移进 DB（按默认空间归档）。"""
    json_path = ctx.data_dir / "cron_jobs.json"
    if not json_path.exists():
        return
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return
    jobs = data.get("jobs", [])
    if not jobs:
        return
    cur = await conn.execute("SELECT COUNT(*) AS c FROM cron_jobs")
    row = await cur.fetchone()
    if row and row["c"] > 0:
        return
    now = int(datetime.now().timestamp() * 1000)
    for job in jobs:
        await conn.execute(
            """INSERT OR IGNORE INTO cron_jobs
               (id, name, description, schedule, command, enabled, last_run, next_run, run_count, created_at, space_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                job.get("id") or str(uuid.uuid4()),
                job.get("name", ""),
                job.get("description", ""),
                job.get("schedule", ""),
                job.get("command", ""),
                1 if job.get("enabled") else 0,
                job.get("lastRun"),
                job.get("nextRun"),
                job.get("runCount", 0),
                job.get("createdAt", now),
                ctx.default_space,
            ),
        )


async def _maybe_migrate_chat_branching(conn: aiosqlite.Connection, ctx: BaselineContext) -> None:
    """为旧库补 parent_id / current_leaf_id 并回填既有扁平消息。"""
    cols = await (await conn.execute("PRAGMA table_info(chat_messages)")).fetchall()
    col_names = {r["name"] for r in cols}
    if "parent_id" not in col_names:
        try:
            await conn.execute("ALTER TABLE chat_messages ADD COLUMN parent_id TEXT")
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise
    conv_cols = {r["name"] for r in await (await conn.execute("PRAGMA table_info(conversations)")).fetchall()}
    if "current_leaf_id" not in conv_cols:
        # SQLite 不支持 ALTER ADD FOREIGN KEY，外键约束在 CREATE TABLE 已声明； ALTER 只补列。
        try:
            await conn.execute("ALTER TABLE conversations ADD COLUMN current_leaf_id TEXT")
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise
    if "metadata" not in conv_cols:
        # 会话级 JSON 配置（RAG 接地等）；旧库补列后默认 NULL。
        try:
            await conn.execute("ALTER TABLE conversations ADD COLUMN metadata TEXT")
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise

    # 回填：没有 parent_id 的消息按 conversation + timestamp 排序，前一条即 parent。
    # 同时把每条 conversation 的 current_leaf_id 设为 timestamp 最大的那条消息。
    # 稳态 fast-path：无待回填行时直接返回，避免逐条 UPDATE 长时间持写锁
    # （多 worker 启动并发时这正是撞锁的热点）。
    _pending = await ctx.fetchone(
        conn, "SELECT COUNT(*) AS n FROM chat_messages WHERE parent_id IS NULL")
    if not _pending or not _pending["n"]:
        return
    rows = await ctx.fetchall(
        conn,
        """
        SELECT id, conversation_id, timestamp
        FROM chat_messages
        WHERE parent_id IS NULL
        ORDER BY conversation_id, timestamp ASC
        """,
    )
    prev_cid: Optional[str] = None
    prev_mid: Optional[str] = None
    last_per_conversation: Dict[str, str] = {}
    for r in rows:
        cid = r["conversation_id"]
        mid = r["id"]
        if cid != prev_cid:
            prev_mid = None
        if prev_mid:
            await conn.execute(
                "UPDATE chat_messages SET parent_id = ? WHERE id = ?",
                (prev_mid, mid),
            )
        last_per_conversation[cid] = mid
        prev_cid = cid
        prev_mid = mid

    # 仅当 conversation 没有 current_leaf_id 时才回填，避免覆盖用户已做的分支切换。
    for cid, leaf_id in last_per_conversation.items():
        await conn.execute(
            """
            UPDATE conversations
            SET current_leaf_id = ?
            WHERE id = ? AND current_leaf_id IS NULL
            """,
            (leaf_id, cid),
        )
