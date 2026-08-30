#!/usr/bin/env python3
"""
SQLite 数据库管理模块（aiosqlite 异步版 + space-key 软隔离）

第 0 层（并发不崩）：
  * 使用 aiosqlite 异步驱动，每个请求独立连接，绝不跨协程/事件循环共享。
  * 连接建立即开启 WAL + synchronous=NORMAL + busy_timeout=5000，避免
    "database is locked" 并支持多 worker 并发读写。

第 1 层（数据隔离）：
  * 全部 29 张业务表包含 `space_id` 列（28 张走通用幂等迁移），存量记录自动归属
    默认空间 `__default__`。
  * 所有读写路径都按 `space_id` 过滤 / 打标；子表（note_links / chat_messages /
    experiment_runs / agent_messages / code_generations）反范式写入父空间。
  * space key 经后端 `deps.get_space_id` 归一（trim + lower）后直接作为 space_id，
    不做 hash。
"""
from __future__ import annotations

import aiosqlite
import sqlite3
import json
import re
import os
import time
import asyncio
import uuid
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Any
from contextlib import asynccontextmanager

# 数据库路径（DATA_DIR 由 backend/server/config.py 在导入本模块前写入环境变量）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get('DATA_DIR', PROJECT_ROOT / 'data'))
DB_PATH = DATA_DIR / 'ai_research_os.db'
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 默认空间：存量数据与 key 恰为 __default__ 的数据归属此处。
DEFAULT_SPACE = "__default__"


def _clean_text_for_db(text: Optional[str]) -> Optional[str]:
    """移除 str 中无法被 utf-8 直接编码的代理码点（surrogates），避免 SQLite 写入时报错。"""
    if text is None:
        return None
    # Python utf-8 默认拒绝 U+D800-U+DFFF；errors='ignore' 会直接丢弃它们，其它合法字符保留。
    return text.encode("utf-8", errors="ignore").decode("utf-8")


# 需要由通用迁移统一补 space_id 列与索引的用户表（28 张）。
# cron_run_history 在建表 DDL 中已原生包含 space_id，因此不进入此迁移列表；
# 当前数据库合计 29 张业务表，全部按 space_id 隔离。
SPACE_TABLES = [
    "papers", "cron_jobs", "software_projects", "tasks", "code_generations",
    "notes", "note_links", "experiments", "experiment_runs", "version_history",
    "conversations", "chat_messages", "agent_sessions", "agent_messages",
    "agent_generated_files", "formula_history", "obsidian_vaults", "obsidian_files",
    "agent_runs", "agent_run_events", "agent_tool_approvals", "agent_replay_messages",
    "agent_teams", "agent_role_templates", "agent_run_nodes",
    "rag_sources", "rag_documents", "rag_chunks",
    "development_run_steps", "development_artifacts",
]


@asynccontextmanager
async def get_db():
    """获取数据库连接的异步上下文管理器。

    每调用一次都会新建一条独立的 aiosqlite 连接（绝不跨协程共享），并在建连后
    立即设置 WAL 相关 PRAGMA。离开上下文时自动提交 / 回滚 / 关闭。

    PRAGMA 顺序很关键：busy_timeout 必须先于 journal_mode 等写操作设置，否则
    多 worker 并发启动（uvicorn --workers N）时 journal_mode 变更会因拿不到锁而
    立刻抛 "database is locked"。这里额外对建连 + 初始 PRAGMA 做有限重试，进一步
    吸收启动期的瞬时锁竞争。
    """
    conn = None
    last_err: Optional[Exception] = None
    # 多 worker 并发 init 时，建连后的首次 PRAGMA 可能撞锁；最多重试几次。
    for attempt in range(5):
        try:
            conn = await aiosqlite.connect(str(DB_PATH))
            conn.row_factory = aiosqlite.Row
            # busy_timeout 必须先设：让后续 journal_mode / 写操作在锁竞争时等待而非立刻失败
            await conn.execute("PRAGMA busy_timeout=5000")
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA synchronous=NORMAL")
            await conn.execute("PRAGMA foreign_keys=ON")
            break
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if conn is not None:
                await conn.close()
                conn = None
            last_err = e
            # 仅在「锁竞争」类错误上重试；其它 OperationalError 直接抛出
            if "database is locked" in msg or "busy" in msg:
                await asyncio.sleep(0.2 * (attempt + 1))
                continue
            raise
    else:
        # 重试耗尽，抛出最后一次错误
        assert last_err is not None
        raise last_err

    try:
        yield conn
        await conn.commit()
    except Exception as e:  # noqa: BLE001 - 统一回滚后向上抛出
        await conn.rollback()
        raise e
    finally:
        await conn.close()


async def _fetchall(conn: aiosqlite.Connection, query: str, params: tuple = ()) -> List[aiosqlite.Row]:
    cur = await conn.execute(query, params)
    return await cur.fetchall()


async def _fetchone(conn: aiosqlite.Connection, query: str, params: tuple = ()) -> Optional[aiosqlite.Row]:
    cur = await conn.execute(query, params)
    return await cur.fetchone()


async def init_db() -> None:
    """初始化数据库表（幂等；安全可重复调用）。

    1. 用 CREATE TABLE IF NOT EXISTS 保证表结构存在（与既有 DDL 完全一致）。
    2. 为 SPACE_TABLES 中的用户表统一补 `space_id` 列 + 索引（新库 / 老库走同一路径）。
       WHERE 过滤 + 索引保证任意空间查询都是单列过滤，无需 JOIN。
    """
    async with get_db() as conn:
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
                id TEXT PRIMARY KEY,
                space_id TEXT NOT NULL DEFAULT '__default__',
                name TEXT,
                target_paths TEXT,            -- JSON 数组：一个或多个目标路径
                recursive INTEGER DEFAULT 1,  -- 是否递归子目录
                file_types TEXT,             -- JSON 数组：如 ["pdf","txt","md"]
                status TEXT DEFAULT 'pending',   -- pending|indexing|ready|partial|failed|cancelled
                doc_count INTEGER DEFAULT 0,
                chunk_count INTEGER DEFAULT 0,
                embedding_model TEXT,
                embed_mode TEXT DEFAULT 'keyword',  -- vector|keyword
                error TEXT,
                created_at INTEGER,
                updated_at INTEGER
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS rag_documents (
                id TEXT PRIMARY KEY,
                space_id TEXT NOT NULL DEFAULT '__default__',
                source_id TEXT,
                file_path TEXT,
                file_name TEXT,
                file_type TEXT,
                file_size INTEGER,
                page_count INTEGER,
                char_count INTEGER,
                chunk_count INTEGER,
                created_at INTEGER
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS rag_chunks (
                id TEXT PRIMARY KEY,
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
                token_count INTEGER,
                created_at INTEGER
            )
        ''')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_rag_sources_space ON rag_sources(space_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_rag_sources_status ON rag_sources(space_id, status)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_rag_documents_space ON rag_documents(space_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_rag_documents_source ON rag_documents(space_id, source_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_rag_chunks_space ON rag_chunks(space_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_rag_chunks_source ON rag_chunks(space_id, source_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_rag_chunks_doc ON rag_chunks(space_id, doc_id)')

        # ==================== space_id 幂等迁移 ====================
        # 新库与老库走同一路径：补列 + 建索引，存量行自动打 __default__。
        # 多 worker 并发 init 时，可能两个进程同时通过 table_info 检查并试图 ALTER，
        # 后到者会撞 "duplicate column"；此处忽略该良性冲突，视为已补列成功。
        for tbl in SPACE_TABLES:
            cols = await (await conn.execute(f"PRAGMA table_info({tbl})")).fetchall()
            col_names = {r["name"] for r in cols}
            if "space_id" not in col_names:
                # NOT NULL + DEFAULT：存量行自动打 __default__；空表也安全。
                try:
                    await conn.execute(
                        f"ALTER TABLE {tbl} ADD COLUMN space_id TEXT NOT NULL DEFAULT '{DEFAULT_SPACE}'"
                    )
                except sqlite3.OperationalError as e:
                    if "duplicate column" in str(e).lower():
                        pass  # 另一 worker 已抢先补列，忽略
                    else:
                        raise
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{tbl}_space ON {tbl}(space_id)"
            )

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
        await _maybe_migrate_cron_json(conn)

        # ==================== chat 消息分叉树迁移 ====================
        # 老库只有扁平线性消息，需补 parent_id / current_leaf_id 并回填。
        await _maybe_migrate_chat_branching(conn)

    print(f"Database initialized at {DB_PATH}")


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


async def _maybe_migrate_cron_json(conn: aiosqlite.Connection) -> None:
    """将遗留的 cron_jobs.json 一次性迁移进 DB（按默认空间归档）。"""
    json_path = DATA_DIR / "cron_jobs.json"
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
                DEFAULT_SPACE,
            ),
        )


async def _maybe_migrate_chat_branching(conn: aiosqlite.Connection) -> None:
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
    rows = await _fetchall(
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


# ==================== 论文相关操作 ====================

def paper_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    """将论文数据库行转换为字典"""
    return {
        'id': row['id'],
        'title': row['title'],
        'authors': json.loads(row['authors']),
        'abstract': row['abstract'],
        'arxivId': row['arxiv_id'],
        'pdfUrl': row['pdf_url'],
        'categories': json.loads(row['categories']) if row['categories'] else [],
        'publishedDate': row['published_date'],
        'localPath': row['local_path'],
        'summary': row['summary'],
        'bibtex': row['bibtex'] if 'bibtex' in row.keys() else None,
        'tags': json.loads(row['tags']) if row['tags'] else [],
        'isRead': bool(row['is_read']),
        'isFavorite': bool(row['is_favorite']),
        'addedAt': row['added_at'],
        'updatedAt': row['updated_at'],
    }


async def get_all_papers(space_id: str = DEFAULT_SPACE, limit: Optional[int] = None, offset: int = 0) -> List[Dict[str, Any]]:
    """获取某空间下所有论文"""
    async with get_db() as conn:
        query = 'SELECT * FROM papers WHERE space_id = ? ORDER BY added_at DESC'
        params: List[Any] = [space_id]
        if limit is not None:
            query += ' LIMIT ? OFFSET ?'
            params.extend([limit, offset])
        rows = await _fetchall(conn, query, params)
        return [paper_to_dict(row) for row in rows]


async def get_paper_by_id(paper_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """根据 ID 获取论文（按空间过滤）"""
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT * FROM papers WHERE id = ? AND space_id = ?', (paper_id, space_id))
        return paper_to_dict(row) if row else None


async def get_paper_by_arxiv(arxiv_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """根据 arXiv ID 获取论文（按空间过滤，用于写前去重）"""
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT * FROM papers WHERE arxiv_id = ? AND space_id = ?', (arxiv_id, space_id))
        return paper_to_dict(row) if row else None


async def insert_paper(paper: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """向某空间插入新论文"""
    try:
        async with get_db() as conn:
            now = int(datetime.now().timestamp())
            arxiv_id = str(paper['arxivId'])
            paper_id = str(paper['id'])
            # arXiv 抓取器历史上把业务标识直接当主键。主键仍需全局唯一，
            # 因此仅对官方抓取形态生成稳定的、带空间维度的存储 ID。
            if paper_id == arxiv_id:
                paper_id = str(uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"ai-research-os://papers/{space_id}/{arxiv_id}",
                ))
            await conn.execute('''
                INSERT INTO papers
                (id, title, authors, abstract, arxiv_id, pdf_url, categories,
                 published_date, local_path, summary, tags, is_read, is_favorite,
                 added_at, updated_at, space_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                paper_id,
                paper['title'],
                json.dumps(paper.get('authors', []), ensure_ascii=False),
                paper['abstract'],
                arxiv_id,
                paper['pdfUrl'],
                json.dumps(paper.get('categories', []), ensure_ascii=False),
                paper['publishedDate'],
                paper.get('localPath'),
                paper.get('summary'),
                json.dumps(paper.get('tags', []), ensure_ascii=False),
                1 if paper.get('isRead') else 0,
                1 if paper.get('isFavorite') else 0,
                paper.get('addedAt', now),
                now,
                space_id,
            ))
            return True
    except sqlite3.IntegrityError:
        # (space_id, arxiv_id) 空间内唯一；重复插入返回 False。
        return False
    except Exception as e:
        print(f"Error inserting paper: {e}")
        return False


async def update_paper(paper_id: str, updates: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """更新某空间论文（WHERE 带 space_id 校验，防误伤他人数据）"""
    try:
        async with get_db() as conn:
            field_mapping = {
                'title': 'title',
                'authors': 'authors',
                'abstract': 'abstract',
                'pdfUrl': 'pdf_url',
                'categories': 'categories',
                'publishedDate': 'published_date',
                'localPath': 'local_path',
                'summary': 'summary',
                'bibtex': 'bibtex',
                'tags': 'tags',
                'isRead': 'is_read',
                'isFavorite': 'is_favorite',
            }
            set_clauses = []
            params: List[Any] = []
            for key, value in updates.items():
                if key in field_mapping:
                    db_field = field_mapping[key]
                    if key in ['authors', 'categories', 'tags']:
                        value = json.dumps(value, ensure_ascii=False)
                    elif key in ['isRead', 'isFavorite']:
                        value = 1 if value else 0
                    set_clauses.append(f"{db_field} = ?")
                    params.append(value)
            if not set_clauses:
                return False
            set_clauses.append("updated_at = ?")
            params.append(int(datetime.now().timestamp()))
            params.append(paper_id)
            params.append(space_id)
            query = f"UPDATE papers SET {', '.join(set_clauses)} WHERE id = ? AND space_id = ?"
            cur = await conn.execute(query, params)
            return cur.rowcount > 0
    except Exception as e:
        print(f"Error updating paper: {e}")
        return False


async def delete_paper(paper_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    """删除某空间论文"""
    try:
        async with get_db() as conn:
            cur = await conn.execute('DELETE FROM papers WHERE id = ? AND space_id = ?', (paper_id, space_id))
            return cur.rowcount > 0
    except Exception as e:
        print(f"Error deleting paper: {e}")
        return False


async def get_papers_count(space_id: Optional[str] = None) -> int:
    """获取论文总数（不传 space_id 时返回全局总数，兼容遗留 CLI）"""
    async with get_db() as conn:
        if space_id:
            cur = await conn.execute('SELECT COUNT(*) FROM papers WHERE space_id = ?', (space_id,))
        else:
            cur = await conn.execute('SELECT COUNT(*) FROM papers')
        return (await cur.fetchone())[0]


# ==================== 数据迁移 ====================

async def migrate_from_json(json_path: Path):
    """从 JSON 文件迁移数据到 SQLite（按默认空间归档）"""
    if not json_path.exists():
        print(f"JSON file not found: {json_path}")
        return
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        papers = data.get('papers', [])
        if not papers:
            print("No papers to migrate")
            return
        print(f"Migrating {len(papers)} papers from JSON to SQLite...")
        success_count = 0
        skip_count = 0
        for paper in papers:
            existing = await get_paper_by_arxiv(paper.get('arxivId', ''), DEFAULT_SPACE)
            if existing:
                skip_count += 1
                continue
            if await insert_paper(paper, DEFAULT_SPACE):
                success_count += 1
            else:
                skip_count += 1
        print(f"Migration complete: {success_count} inserted, {skip_count} skipped")
        backup_path = json_path.with_suffix('.json.backup')
        json_path.rename(backup_path)
        print(f"Original JSON backed up to: {backup_path}")
    except Exception as e:
        print(f"Migration error: {e}")


# ==================== 任务相关操作 ====================

def task_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    """将任务数据库行转换为字典"""
    return {
        'id': row['id'],
        'title': row['title'],
        'description': row['description'],
        'status': row['status'],
        'priority': row['priority'],
        'deadline': row['deadline'],
        'tags': json.loads(row['tags']) if row['tags'] else [],
        'projectId': row['project_id'],
        'parentTaskId': row['parent_task_id'],
        'aiSuggested': bool(row['ai_suggested']),
        'completedAt': row['completed_at'],
        'createdAt': row['created_at'],
        'updatedAt': row['updated_at'],
    }


async def get_all_tasks(space_id: str = DEFAULT_SPACE, project_id: Optional[str] = None,
                        status: Optional[str] = None) -> List[Dict[str, Any]]:
    """获取某空间任务，支持按项目和状态筛选"""
    async with get_db() as conn:
        query = 'SELECT * FROM tasks WHERE space_id = ?'
        params: List[Any] = [space_id]
        if project_id:
            query += ' AND project_id = ?'
            params.append(project_id)
        if status:
            query += ' AND status = ?'
            params.append(status)
        query += ' ORDER BY priority DESC, created_at DESC'
        rows = await _fetchall(conn, query, params)
        return [task_to_dict(row) for row in rows]


async def get_task_by_id(task_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """根据 ID 获取任务（按空间过滤）"""
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT * FROM tasks WHERE id = ? AND space_id = ?', (task_id, space_id))
        return task_to_dict(row) if row else None


async def insert_task(task: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """向某空间插入新任务"""
    try:
        async with get_db() as conn:
            now = int(datetime.now().timestamp())
            await conn.execute('''
                INSERT INTO tasks
                (id, title, description, status, priority, deadline, tags,
                 project_id, parent_task_id, ai_suggested, completed_at, created_at, updated_at, space_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                task['id'],
                task['title'],
                task.get('description', ''),
                task.get('status', 'todo'),
                task.get('priority', 'medium'),
                task.get('deadline'),
                json.dumps(task.get('tags', []), ensure_ascii=False),
                task.get('projectId'),
                task.get('parentTaskId'),
                1 if task.get('aiSuggested') else 0,
                task.get('completedAt'),
                task.get('createdAt', now),
                now,
                space_id,
            ))
            return True
    except Exception as e:
        print(f"Insert task error: {e}")
        return False


async def update_task(task_id: str, updates: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """更新某空间任务（先按空间取当前值生成版本，再按空间更新）"""
    try:
        async with get_db() as conn:
            allowed_fields = {
                'title', 'description', 'status', 'priority', 'deadline',
                'tags', 'projectId', 'parentTaskId', 'completedAt',
            }
            updates = {k: v for k, v in updates.items() if k in allowed_fields}
            if not updates:
                return False
            current_task = await get_task_by_id(task_id, space_id)
            if current_task:
                change_summary = ', '.join([f"{k}={v}" for k, v in updates.items()])
                await create_version('task', task_id, current_task, change_summary, space_id=space_id)
            field_mapping = {
                'projectId': 'project_id',
                'parentTaskId': 'parent_task_id',
                'completedAt': 'completed_at',
            }
            set_clauses: List[str] = []
            values: List[Any] = []
            for key, value in updates.items():
                db_key = field_mapping.get(key, key)
                set_clauses.append(f"{db_key} = ?")
                if key == 'tags':
                    values.append(json.dumps(value, ensure_ascii=False))
                else:
                    values.append(value)
            set_clauses.append("updated_at = ?")
            values.append(int(datetime.now().timestamp()))
            values.append(task_id)
            values.append(space_id)
            query = f"UPDATE tasks SET {', '.join(set_clauses)} WHERE id = ? AND space_id = ?"
            cur = await conn.execute(query, values)
            return cur.rowcount > 0
    except Exception as e:
        print(f"Update task error: {e}")
        return False


async def delete_task(task_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    """删除某空间任务"""
    try:
        async with get_db() as conn:
            cur = await conn.execute('DELETE FROM tasks WHERE id = ? AND space_id = ?', (task_id, space_id))
            return cur.rowcount > 0
    except Exception as e:
        print(f"Delete task error: {e}")
        return False


async def get_tasks_by_project(project_id: str, space_id: str = DEFAULT_SPACE) -> List[Dict[str, Any]]:
    """获取指定项目在某空间下的所有任务"""
    async with get_db() as conn:
        rows = await _fetchall(
            conn,
            '''SELECT * FROM tasks WHERE project_id = ? AND space_id = ?
               ORDER BY priority DESC, created_at DESC''',
            (project_id, space_id),
        )
        return [task_to_dict(row) for row in rows]


# ==================== 软件项目相关操作 ====================

def project_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    """将项目数据库行转换为字典"""
    return {
        'id': row['id'],
        'name': row['name'],
        'description': row['description'],
        'ideaDescription': row['idea_description'],
        'techStack': json.loads(row['tech_stack']) if row['tech_stack'] else [],
        'status': row['status'],
        'localPath': row['local_path'],
        'githubUrl': row['github_url'],
        'architecture': json.loads(row['architecture']) if row['architecture'] else {},
        'features': json.loads(row['features']) if row['features'] else [],
        'milestones': json.loads(row['milestones']) if row['milestones'] else [],
        'aiGeneratedCode': bool(row['ai_generated_code']),
        'developmentConfig': (json.loads(row['development_config'])
                              if 'development_config' in row.keys() and row['development_config'] else {}),
        'createdAt': row['created_at'],
        'updatedAt': row['updated_at'],
    }


async def get_all_projects(space_id: str = DEFAULT_SPACE, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """获取某空间项目，支持按状态筛选"""
    async with get_db() as conn:
        query = 'SELECT * FROM software_projects WHERE space_id = ?'
        params: List[Any] = [space_id]
        if status:
            query += ' AND status = ?'
            params.append(status)
        query += ' ORDER BY updated_at DESC'
        rows = await _fetchall(conn, query, params)
        return [project_to_dict(row) for row in rows]


async def get_project_by_id(project_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """根据 ID 获取项目（按空间过滤）"""
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT * FROM software_projects WHERE id = ? AND space_id = ?', (project_id, space_id))
        return project_to_dict(row) if row else None


async def insert_project(project: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """向某空间插入新项目"""
    try:
        async with get_db() as conn:
            now = int(datetime.now().timestamp())
            await conn.execute('''
                INSERT INTO software_projects
                (id, name, description, idea_description, tech_stack, status, local_path,
                 github_url, architecture, features, milestones, ai_generated_code, created_at, updated_at, space_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                project['id'],
                project['name'],
                project.get('description', ''),
                project.get('ideaDescription', ''),
                json.dumps(project.get('techStack', []), ensure_ascii=False),
                project.get('status', 'design'),
                project.get('localPath'),
                project.get('githubUrl'),
                json.dumps(project.get('architecture', {}), ensure_ascii=False),
                json.dumps(project.get('features', []), ensure_ascii=False),
                json.dumps(project.get('milestones', []), ensure_ascii=False),
                1 if project.get('aiGeneratedCode') else 0,
                project.get('createdAt', now),
                now,
                space_id,
            ))
            return True
    except Exception as e:
        print(f"Insert project error: {e}")
        return False


async def update_project(project_id: str, updates: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """更新某空间项目"""
    try:
        async with get_db() as conn:
            allowed_fields = {
                'name', 'description', 'ideaDescription', 'techStack', 'status',
                'localPath', 'githubUrl', 'architecture', 'features', 'milestones', 'aiGeneratedCode',
                'developmentConfig',
            }
            updates = {k: v for k, v in updates.items() if k in allowed_fields}
            if not updates:
                return False
            field_mapping = {
                'ideaDescription': 'idea_description',
                'techStack': 'tech_stack',
                'localPath': 'local_path',
                'githubUrl': 'github_url',
                'aiGeneratedCode': 'ai_generated_code',
                'developmentConfig': 'development_config',
            }
            set_clauses: List[str] = []
            values: List[Any] = []
            for key, value in updates.items():
                db_key = field_mapping.get(key, key)
                set_clauses.append(f"{db_key} = ?")
                if key in ['techStack', 'architecture', 'features', 'milestones', 'developmentConfig']:
                    values.append(json.dumps(value, ensure_ascii=False))
                elif key == 'aiGeneratedCode':
                    values.append(1 if value else 0)
                else:
                    values.append(value)
            set_clauses.append("updated_at = ?")
            values.append(int(datetime.now().timestamp()))
            values.append(project_id)
            values.append(space_id)
            query = f"UPDATE software_projects SET {', '.join(set_clauses)} WHERE id = ? AND space_id = ?"
            cur = await conn.execute(query, values)
            return cur.rowcount > 0
    except Exception as e:
        print(f"Update project error: {e}")
        return False


async def delete_project(project_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    """删除某空间项目（级联删除关联任务和代码生成记录）"""
    try:
        async with get_db() as conn:
            cur = await conn.execute(
                'DELETE FROM software_projects WHERE id = ? AND space_id = ?', (project_id, space_id))
            return cur.rowcount > 0
    except Exception as e:
        print(f"Delete project error: {e}")
        return False


# ==================== 代码生成相关操作 ====================

def code_gen_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    """将代码生成记录数据库行转换为字典"""
    return {
        'id': row['id'],
        'projectId': row['project_id'],
        'prompt': row['prompt'],
        'generatedCode': row['generated_code'],
        'filePath': row['file_path'],
        'language': row['language'],
        'status': row['status'],
        'createdAt': row['created_at'],
    }


async def get_code_generations_by_project(project_id: str, space_id: str = DEFAULT_SPACE) -> List[Dict[str, Any]]:
    """获取某空间项目下的代码生成历史"""
    async with get_db() as conn:
        rows = await _fetchall(
            conn,
            '''SELECT * FROM code_generations WHERE project_id = ? AND space_id = ?
               ORDER BY created_at DESC''',
            (project_id, space_id),
        )
        return [code_gen_to_dict(row) for row in rows]


async def insert_code_generation(code_gen: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """向某空间插入代码生成记录（反范式写入父空间）"""
    try:
        async with get_db() as conn:
            now = int(datetime.now().timestamp())
            await conn.execute('''
                INSERT INTO code_generations
                (id, project_id, prompt, generated_code, file_path, language, status, created_at, space_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                code_gen['id'],
                code_gen['projectId'],
                code_gen['prompt'],
                code_gen['generatedCode'],
                code_gen.get('filePath'),
                code_gen.get('language'),
                code_gen.get('status', 'pending'),
                code_gen.get('createdAt', now),
                space_id,
            ))
            return True
    except Exception as e:
        print(f"Insert code generation error: {e}")
        return False


async def update_code_generation_status(code_gen_id: str, status: str, space_id: str = DEFAULT_SPACE) -> bool:
    """更新代码生成记录状态"""
    try:
        async with get_db() as conn:
            cur = await conn.execute(
                'UPDATE code_generations SET status = ? WHERE id = ? AND space_id = ?',
                (status, code_gen_id, space_id))
            return cur.rowcount > 0
    except Exception as e:
        print(f"Update code generation status error: {e}")
        return False


# ==================== 笔记相关操作 ====================

def note_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    """将笔记数据库行转换为字典"""
    return {
        'id': row['id'],
        'title': row['title'],
        'content': row['content'],
        'summary': row['summary'],
        'type': row['type'],
        'tags': json.loads(row['tags']) if row['tags'] else [],
        'paperId': row['paper_id'],
        'projectId': row['project_id'],
        'parentNoteId': row['parent_note_id'],
        'isFavorite': bool(row['is_favorite']),
        'aiGenerated': bool(row['ai_generated']),
        'createdAt': row['created_at'],
        'updatedAt': row['updated_at'],
    }


async def get_all_notes(space_id: str = DEFAULT_SPACE, note_type: Optional[str] = None,
                        paper_id: Optional[str] = None, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """获取某空间笔记，支持按类型、论文、项目筛选"""
    async with get_db() as conn:
        query = 'SELECT * FROM notes WHERE space_id = ?'
        params: List[Any] = [space_id]
        if note_type:
            query += ' AND type = ?'
            params.append(note_type)
        if paper_id:
            query += ' AND paper_id = ?'
            params.append(paper_id)
        if project_id:
            query += ' AND project_id = ?'
            params.append(project_id)
        query += ' ORDER BY updated_at DESC'
        rows = await _fetchall(conn, query, params)
        return [note_to_dict(row) for row in rows]


async def get_note_by_id(note_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """根据 ID 获取笔记（按空间过滤）"""
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT * FROM notes WHERE id = ? AND space_id = ?', (note_id, space_id))
        return note_to_dict(row) if row else None


async def get_note_links(note_id: str, space_id: str = DEFAULT_SPACE) -> List[str]:
    """获取笔记的链接目标 ID 列表（按空间过滤）"""
    async with get_db() as conn:
        rows = await _fetchall(
            conn, 'SELECT target_note_id FROM note_links WHERE source_note_id = ? AND space_id = ?',
            (note_id, space_id))
        return [row['target_note_id'] for row in rows]


async def get_linked_notes(note_id: str, space_id: str = DEFAULT_SPACE) -> List[str]:
    """获取链接到该笔记的源笔记 ID 列表（按空间过滤）"""
    async with get_db() as conn:
        rows = await _fetchall(
            conn, 'SELECT source_note_id FROM note_links WHERE target_note_id = ? AND space_id = ?',
            (note_id, space_id))
        return [row['source_note_id'] for row in rows]


async def insert_note(note: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """向某空间插入新笔记"""
    try:
        async with get_db() as conn:
            now = int(datetime.now().timestamp())
            await conn.execute('''
                INSERT INTO notes
                (id, title, content, summary, type, tags, paper_id, project_id, parent_note_id,
                 is_favorite, ai_generated, created_at, updated_at, space_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                note['id'],
                note['title'],
                note.get('content', ''),
                note.get('summary'),
                note.get('type', 'note'),
                json.dumps(note.get('tags', []), ensure_ascii=False),
                note.get('paperId'),
                note.get('projectId'),
                note.get('parentNoteId'),
                1 if note.get('isFavorite') else 0,
                1 if note.get('aiGenerated') else 0,
                note.get('createdAt', now),
                now,
                space_id,
            ))
            return True
    except Exception as e:
        print(f"Insert note error: {e}")
        return False


async def update_note(note_id: str, updates: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """更新某空间笔记（先按空间取当前值生成版本，再按空间更新）"""
    try:
        async with get_db() as conn:
            allowed_fields = {
                'title', 'content', 'summary', 'type', 'tags',
                'paperId', 'projectId', 'parentNoteId', 'isFavorite', 'aiGenerated',
            }
            updates = {k: v for k, v in updates.items() if k in allowed_fields}
            if not updates:
                return False
            current_note = await get_note_by_id(note_id, space_id)
            if current_note:
                change_summary = f"更新: {', '.join(updates.keys())}"
                await create_version('note', note_id, current_note, change_summary, space_id=space_id)
            field_mapping = {
                'paperId': 'paper_id',
                'projectId': 'project_id',
                'parentNoteId': 'parent_note_id',
                'isFavorite': 'is_favorite',
                'aiGenerated': 'ai_generated',
            }
            set_clauses: List[str] = []
            values: List[Any] = []
            for key, value in updates.items():
                db_key = field_mapping.get(key, key)
                set_clauses.append(f"{db_key} = ?")
                if key == 'tags':
                    values.append(json.dumps(value, ensure_ascii=False))
                elif key in ['isFavorite', 'aiGenerated']:
                    values.append(1 if value else 0)
                else:
                    values.append(value)
            set_clauses.append("updated_at = ?")
            values.append(int(datetime.now().timestamp()))
            values.append(note_id)
            values.append(space_id)
            query = f"UPDATE notes SET {', '.join(set_clauses)} WHERE id = ? AND space_id = ?"
            cur = await conn.execute(query, values)
            return cur.rowcount > 0
    except Exception as e:
        print(f"Update note error: {e}")
        return False


async def delete_note(note_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    """删除某空间笔记（级联删除 note_links，且严格限定本空间）"""
    try:
        async with get_db() as conn:
            cur = await conn.execute('DELETE FROM notes WHERE id = ? AND space_id = ?', (note_id, space_id))
            await conn.execute(
                'DELETE FROM note_links WHERE (source_note_id = ? OR target_note_id = ?) AND space_id = ?',
                (note_id, note_id, space_id))
            return cur.rowcount > 0
    except Exception as e:
        print(f"Delete note error: {e}")
        return False


async def add_note_link(source_note_id: str, target_note_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    """添加笔记链接（反范式写入父空间，便于按空间过滤）"""
    try:
        async with get_db() as conn:
            now = int(datetime.now().timestamp())
            await conn.execute('''
                INSERT OR IGNORE INTO note_links (source_note_id, target_note_id, created_at, space_id)
                VALUES (?, ?, ?, ?)
            ''', (source_note_id, target_note_id, now, space_id))
            return True
    except Exception as e:
        print(f"Add note link error: {e}")
        return False


# ==================== 实验相关操作 ====================

def experiment_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    """将实验数据库行转换为字典"""
    return {
        'id': row['id'],
        'name': row['name'],
        'description': row['description'],
        'projectId': row['project_id'],
        'status': row['status'],
        'config': json.loads(row['config']) if row['config'] else {},
        'tags': json.loads(row['tags']) if row['tags'] else [],
        'swanlabProject': row['swanlab_project'],
        'swanlabExperimentId': row['swanlab_experiment_id'],
        'totalRuns': row['total_runs'],
        'bestMetricName': row['best_metric_name'],
        'bestMetricValue': row['best_metric_value'],
        'createdAt': row['created_at'],
        'updatedAt': row['updated_at'],
    }


def run_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    """将实验运行记录数据库行转换为字典"""
    return {
        'id': row['id'],
        'experimentId': row['experiment_id'],
        'runNumber': row['run_number'],
        'status': row['status'],
        'config': json.loads(row['config']) if row['config'] else {},
        'metrics': json.loads(row['metrics']) if row['metrics'] else {},
        'swanlabRunId': row['swanlab_run_id'],
        'startedAt': row['started_at'],
        'endedAt': row['ended_at'],
        'duration': row['duration'],
    }


async def get_all_experiments(space_id: str = DEFAULT_SPACE, status: Optional[str] = None,
                              project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """获取某空间实验"""
    async with get_db() as conn:
        query = 'SELECT * FROM experiments WHERE space_id = ?'
        params: List[Any] = [space_id]
        if status:
            query += ' AND status = ?'
            params.append(status)
        if project_id:
            query += ' AND project_id = ?'
            params.append(project_id)
        query += ' ORDER BY updated_at DESC'
        rows = await _fetchall(conn, query, params)
        return [experiment_to_dict(row) for row in rows]


async def get_experiment_by_id(experiment_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """根据 ID 获取实验（按空间过滤）"""
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT * FROM experiments WHERE id = ? AND space_id = ?', (experiment_id, space_id))
        return experiment_to_dict(row) if row else None


async def get_experiment_runs(experiment_id: str, space_id: str = DEFAULT_SPACE) -> List[Dict[str, Any]]:
    """获取某空间实验的所有运行记录（反范式按空间过滤）"""
    async with get_db() as conn:
        rows = await _fetchall(
            conn,
            'SELECT * FROM experiment_runs WHERE experiment_id = ? AND space_id = ? ORDER BY run_number DESC',
            (experiment_id, space_id))
        return [run_to_dict(row) for row in rows]


async def insert_experiment(experiment: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """向某空间插入新实验"""
    try:
        async with get_db() as conn:
            now = int(datetime.now().timestamp())
            await conn.execute('''
                INSERT INTO experiments
                (id, name, description, project_id, status, config, tags, swanlab_project,
                 swanlab_experiment_id, total_runs, created_at, updated_at, space_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                experiment['id'],
                experiment['name'],
                experiment.get('description', ''),
                experiment.get('projectId'),
                experiment.get('status', 'planning'),
                json.dumps(experiment.get('config', {}), ensure_ascii=False),
                json.dumps(experiment.get('tags', []), ensure_ascii=False),
                experiment.get('swanlabProject'),
                experiment.get('swanlabExperimentId'),
                experiment.get('totalRuns', 0),
                experiment.get('createdAt', now),
                now,
                space_id,
            ))
            return True
    except Exception as e:
        print(f"Insert experiment error: {e}")
        return False


async def update_experiment(experiment_id: str, updates: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """更新某空间实验"""
    try:
        async with get_db() as conn:
            allowed_fields = {
                'name', 'description', 'projectId', 'status', 'config', 'tags',
                'swanlabProject', 'swanlabExperimentId', 'totalRuns', 'bestMetricName', 'bestMetricValue',
            }
            updates = {k: v for k, v in updates.items() if k in allowed_fields}
            if not updates:
                return False
            field_mapping = {
                'projectId': 'project_id',
                'swanlabProject': 'swanlab_project',
                'swanlabExperimentId': 'swanlab_experiment_id',
                'totalRuns': 'total_runs',
                'bestMetricName': 'best_metric_name',
                'bestMetricValue': 'best_metric_value',
            }
            set_clauses: List[str] = []
            values: List[Any] = []
            for key, value in updates.items():
                db_key = field_mapping.get(key, key)
                set_clauses.append(f"{db_key} = ?")
                if key in ['config', 'tags']:
                    values.append(json.dumps(value, ensure_ascii=False))
                else:
                    values.append(value)
            set_clauses.append("updated_at = ?")
            values.append(int(datetime.now().timestamp()))
            values.append(experiment_id)
            values.append(space_id)
            query = f"UPDATE experiments SET {', '.join(set_clauses)} WHERE id = ? AND space_id = ?"
            cur = await conn.execute(query, values)
            return cur.rowcount > 0
    except Exception as e:
        print(f"Update experiment error: {e}")
        return False


async def delete_experiment(experiment_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    """删除某空间实验"""
    try:
        async with get_db() as conn:
            cur = await conn.execute('DELETE FROM experiments WHERE id = ? AND space_id = ?', (experiment_id, space_id))
            return cur.rowcount > 0
    except Exception as e:
        print(f"Delete experiment error: {e}")
        return False


async def insert_experiment_run(run: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """插入实验运行记录（反范式写入父空间）"""
    try:
        async with get_db() as conn:
            await conn.execute('''
                INSERT INTO experiment_runs
                (id, experiment_id, run_number, status, config, metrics, swanlab_run_id, started_at, ended_at, duration, space_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                run['id'],
                run['experimentId'],
                run['runNumber'],
                run.get('status', 'running'),
                json.dumps(run.get('config', {}), ensure_ascii=False),
                json.dumps(run.get('metrics', {}), ensure_ascii=False),
                run.get('swanlabRunId'),
                run['startedAt'],
                run.get('endedAt'),
                run.get('duration'),
                space_id,
            ))
            return True
    except Exception as e:
        print(f"Insert experiment run error: {e}")
        return False


async def update_experiment_run(run_id: str, updates: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """更新实验运行记录"""
    try:
        async with get_db() as conn:
            allowed_fields = {'status', 'metrics', 'endedAt', 'duration'}
            updates = {k: v for k, v in updates.items() if k in allowed_fields}
            if not updates:
                return False
            field_mapping = {'endedAt': 'ended_at'}
            set_clauses: List[str] = []
            values: List[Any] = []
            for key, value in updates.items():
                db_key = field_mapping.get(key, key)
                set_clauses.append(f"{db_key} = ?")
                if key == 'metrics':
                    values.append(json.dumps(value, ensure_ascii=False))
                else:
                    values.append(value)
            values.append(run_id)
            values.append(space_id)
            query = f"UPDATE experiment_runs SET {', '.join(set_clauses)} WHERE id = ? AND space_id = ?"
            cur = await conn.execute(query, values)
            return cur.rowcount > 0
    except Exception as e:
        print(f"Update experiment run error: {e}")
        return False


# ==================== 版本历史操作 ====================

async def create_version(entity_type: str, entity_id: str, data: Dict[str, Any],
                         change_summary: str = '', created_by: str = 'user',
                         space_id: str = DEFAULT_SPACE) -> bool:
    """创建新版本记录（按空间生成版本号）"""
    try:
        async with get_db() as conn:
            row = await _fetchone(
                conn,
                'SELECT MAX(version_number) as max_version FROM version_history WHERE entity_id = ? AND space_id = ?',
                (entity_id, space_id))
            next_version = (row['max_version'] or 0) + 1
            version_id = str(uuid.uuid4())
            now = int(datetime.now().timestamp())
            await conn.execute('''
                INSERT INTO version_history
                (id, entity_type, entity_id, version_number, data, change_summary, created_by, created_at, space_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                version_id,
                entity_type,
                entity_id,
                next_version,
                json.dumps(data, ensure_ascii=False),
                change_summary,
                created_by,
                now,
                space_id,
            ))
            return True
    except Exception as e:
        print(f"Create version error: {e}")
        return False


async def get_versions(entity_type: str, entity_id: str, limit: int = 50,
                       space_id: str = DEFAULT_SPACE) -> List[Dict[str, Any]]:
    """获取某空间实体的版本历史"""
    async with get_db() as conn:
        rows = await _fetchall(
            conn,
            '''SELECT * FROM version_history
               WHERE entity_type = ? AND entity_id = ? AND space_id = ?
               ORDER BY version_number DESC LIMIT ?''',
            (entity_type, entity_id, space_id, limit))
        return [_version_row_to_dict(row) for row in rows]


async def get_version_by_id(version_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """根据ID获取特定版本（按空间过滤）"""
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT * FROM version_history WHERE id = ? AND space_id = ?', (version_id, space_id))
        return _version_row_to_dict(row) if row else None


def _version_row_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    return {
        'id': row['id'],
        'entityType': row['entity_type'],
        'entityId': row['entity_id'],
        'versionNumber': row['version_number'],
        'data': json.loads(row['data']),
        'changeSummary': row['change_summary'],
        'createdBy': row['created_by'],
        'createdAt': row['created_at'],
    }


async def compare_versions(version_id1: str, version_id2: str, space_id: str = DEFAULT_SPACE) -> Dict[str, Any]:
    """对比两个版本的差异（按空间过滤）"""
    v1 = await get_version_by_id(version_id1, space_id)
    v2 = await get_version_by_id(version_id2, space_id)
    if not v1 or not v2:
        return {'error': 'Version not found'}
    diff = {'added': {}, 'removed': {}, 'modified': {}}
    data1 = v1['data']
    data2 = v2['data']
    all_keys = set(data1.keys()) | set(data2.keys())
    for key in all_keys:
        if key not in data1:
            diff['added'][key] = data2[key]
        elif key not in data2:
            diff['removed'][key] = data1[key]
        elif data1[key] != data2[key]:
            diff['modified'][key] = {'old': data1[key], 'new': data2[key]}
    return {'version1': v1, 'version2': v2, 'diff': diff}


async def restore_version(version_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """恢复到指定版本（在本空间内新建版本）"""
    version = await get_version_by_id(version_id, space_id)
    if not version:
        return None
    await create_version(
        entity_type=version['entityType'],
        entity_id=version['entityId'],
        data=version['data'],
        change_summary=f"恢复到版本 #{version['versionNumber']}",
        created_by='system',
        space_id=space_id,
    )
    return version['data']


async def delete_old_versions(entity_type: str, entity_id: str, keep_count: int = 20,
                              space_id: str = DEFAULT_SPACE) -> int:
    """删除旧版本，只保留最近的N个（按空间过滤）"""
    try:
        async with get_db() as conn:
            rows = await _fetchall(
                conn,
                '''SELECT id FROM version_history
                   WHERE entity_type = ? AND entity_id = ? AND space_id = ?
                   ORDER BY version_number DESC LIMIT -1 OFFSET ?''',
                (entity_type, entity_id, space_id, keep_count))
            ids_to_delete = [row['id'] for row in rows]
            if ids_to_delete:
                placeholders = ','.join(['?'] * len(ids_to_delete))
                await conn.execute(f"DELETE FROM version_history WHERE id IN ({placeholders})", ids_to_delete)
            return len(ids_to_delete)
    except Exception as e:
        print(f"Delete old versions error: {e}")
        return 0


# ==================== 对话相关操作 ====================

def _coerce_json_field(raw: Any) -> Dict[str, Any]:
    """把 SQLite 存的 JSON 文本安全地还原为 dict；空 / 非法返回 {}。"""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


async def get_all_conversations(space_id: str = DEFAULT_SPACE) -> List[Dict[str, Any]]:
    """获取某空间所有对话列表"""
    async with get_db() as conn:
        rows = await _fetchall(
            conn, 'SELECT * FROM conversations WHERE space_id = ? ORDER BY updated_at DESC', (space_id,))
        return [
            {
                'id': row['id'],
                'title': row['title'],
                'currentLeafId': row['current_leaf_id'] if 'current_leaf_id' in row.keys() else None,
                'createdAt': row['created_at'],
                'updatedAt': row['updated_at'],
                'metadata': _coerce_json_field(row['metadata']) if 'metadata' in row.keys() else {},
            }
            for row in rows
        ]


def _encode_chat_content(content):
    """聊天消息 content 透明编码：list/dict -> JSON 字符串（便于存入 TEXT 列），
    str/None 原样返回。配合 _decode_chat_content 实现多模态消息持久化。"""
    if isinstance(content, (list, dict)):
        return json.dumps(content, ensure_ascii=False)
    return content


def _decode_chat_content(raw):
    """聊天消息 content 透明解码：以 [ 或 { 开头的字符串尝试解析为 JSON，
    失败则原样返回（兼容纯文本消息，且避免误判以 [ 开头的普通文本）。"""
    if isinstance(raw, str):
        s = raw.strip()
        if s.startswith(('[', '{')):
            try:
                return json.loads(s)
            except (ValueError, TypeError):
                return raw
    return raw


async def _row_to_message(m: aiosqlite.Row) -> Dict[str, Any]:
    """把 chat_messages 行转为前端可用的消息字典。"""
    return {
        'id': m['id'],
        'role': m['role'],
        'content': _decode_chat_content(m['content']),
        'timestamp': m['timestamp'],
        'metadata': json.loads(m['metadata']) if m['metadata'] else {},
        'parentId': m['parent_id'] if 'parent_id' in m.keys() else None,
    }


async def get_message_path(conn: aiosqlite.Connection, conversation_id: str, leaf_id: Optional[str], space_id: str) -> List[Dict[str, Any]]:
    """从 leaf_id 沿 parent_id 链向上遍历到根，返回正序消息列表（根 → 叶）。

    leaf_id 为 None 时返回空列表。同时为每条消息附加 siblingCount 和 siblingIndex，
    供前端渲染分支切换箭头。
    """
    if not leaf_id:
        return []
    chain: List[Dict[str, Any]] = []
    visited: set = set()
    cur_id: Optional[str] = leaf_id
    while cur_id and cur_id not in visited:
        visited.add(cur_id)
        row = await _fetchone(
            conn,
            "SELECT * FROM chat_messages WHERE id = ? AND conversation_id = ? AND space_id = ?",
            (cur_id, conversation_id, space_id),
        )
        if not row:
            break
        msg = await _row_to_message(row)
        chain.append(msg)
        cur_id = row["parent_id"]
    chain.reverse()

    # 为每条消息附加兄弟数信息（同一 parent_id 下的消息数）
    for msg in chain:
        parent_id = msg.get("parentId")
        if parent_id:
            sib_rows = await _fetchall(
                conn,
                "SELECT id FROM chat_messages WHERE conversation_id = ? AND space_id = ? AND parent_id = ? ORDER BY timestamp ASC",
                (conversation_id, space_id, parent_id),
            )
        else:
            sib_rows = await _fetchall(
                conn,
                "SELECT id FROM chat_messages WHERE conversation_id = ? AND space_id = ? AND parent_id IS NULL ORDER BY timestamp ASC",
                (conversation_id, space_id),
            )
        sibling_ids = [r["id"] for r in sib_rows]
        msg["siblingCount"] = len(sibling_ids)
        msg["siblingIndex"] = sibling_ids.index(msg["id"]) if msg["id"] in sibling_ids else 0
        msg["siblingIds"] = sibling_ids
    return chain


async def get_conversation_by_id(conversation_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """获取单个对话详情（含当前分支消息，均按空间过滤）。

    返回的 messages 是从根到 current_leaf_id 的路径；每条消息含 siblingCount /
    siblingIndex / siblingIds 供前端渲染分支切换。
    """
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT * FROM conversations WHERE id = ? AND space_id = ?', (conversation_id, space_id))
        if not row:
            return None
        leaf_id = row['current_leaf_id'] if 'current_leaf_id' in row.keys() else None
        messages = await get_message_path(conn, conversation_id, leaf_id, space_id)
        return {
            'id': row['id'],
            'title': row['title'],
            'currentLeafId': leaf_id,
            'createdAt': row['created_at'],
            'updatedAt': row['updated_at'],
            'metadata': _coerce_json_field(row['metadata']) if 'metadata' in row.keys() else {},
            'messages': messages,
        }


async def insert_conversation(conversation: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """插入新对话（会话与消息均按空间打标；自动维护 current_leaf_id）。"""
    try:
        async with get_db() as conn:
            messages = conversation.get('messages', [])
            leaf_id = messages[-1]['id'] if messages else None
            await conn.execute(
                'INSERT INTO conversations (id, title, current_leaf_id, created_at, updated_at, metadata, space_id) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (conversation['id'], conversation.get('title', '新对话'), leaf_id,
                 conversation['createdAt'], conversation['updatedAt'],
                 json.dumps(conversation.get('metadata', {})), space_id))
            prev_id: Optional[str] = None
            for msg in messages:
                await conn.execute('''
                    INSERT INTO chat_messages (id, conversation_id, parent_id, role, content, timestamp, metadata, space_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    msg['id'], conversation['id'], prev_id, msg['role'], msg['content'],
                    msg['timestamp'], json.dumps(msg.get('metadata', {})), space_id))
                prev_id = msg['id']
            return True
    except Exception as e:
        print(f"Insert conversation error: {e}")
        return False


async def update_conversation(conversation_id: str, updates: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """更新对话信息（按空间校验）"""
    try:
        async with get_db() as conn:
            rowcount = 0
            if 'title' in updates:
                cur = await conn.execute(
                    'UPDATE conversations SET title = ?, updated_at = ? WHERE id = ? AND space_id = ?',
                    (updates['title'], int(datetime.now().timestamp() * 1000), conversation_id, space_id))
                rowcount += cur.rowcount
            if 'metadata' in updates:
                cur = await conn.execute(
                    'UPDATE conversations SET metadata = ?, updated_at = ? WHERE id = ? AND space_id = ?',
                    (json.dumps(updates['metadata']), int(datetime.now().timestamp() * 1000), conversation_id, space_id))
                rowcount += cur.rowcount
            if 'updatedAt' in updates:
                cur = await conn.execute(
                    'UPDATE conversations SET updated_at = ? WHERE id = ? AND space_id = ?',
                    (updates['updatedAt'], conversation_id, space_id))
                rowcount += cur.rowcount
            return rowcount > 0
    except Exception as e:
        print(f"Update conversation error: {e}")
        return False


async def delete_conversation(conversation_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    """删除对话（关联消息随外键级联删除；严格限定本空间）"""
    try:
        async with get_db() as conn:
            cur = await conn.execute('DELETE FROM conversations WHERE id = ? AND space_id = ?', (conversation_id, space_id))
            return cur.rowcount > 0
    except Exception as e:
        print(f"Delete conversation error: {e}")
        return False


async def insert_chat_message(message: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """插入单条聊天消息（按空间打标；自动设置 parent_id 并更新 current_leaf_id）。

    message 可选传入 ``parentId`` 指定父消息；不传则尝试取会话当前 current_leaf_id。
    插入后把会话的 current_leaf_id 更新为本消息 id。
    """
    try:
        async with get_db() as conn:
            conv_id = message['conversationId']
            parent_id = message.get('parentId')
            if not parent_id:
                row = await _fetchone(
                    conn,
                    "SELECT current_leaf_id FROM conversations WHERE id = ? AND space_id = ?",
                    (conv_id, space_id),
                )
                if row:
                    parent_id = row["current_leaf_id"]
            await conn.execute('''
                INSERT INTO chat_messages (id, conversation_id, parent_id, role, content, timestamp, metadata, space_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                message['id'],
                conv_id,
                parent_id,
                message['role'],
                _encode_chat_content(message['content']),
                message['timestamp'],
                json.dumps(message.get('metadata', {})),
                space_id,
            ))
            now = int(time.time() * 1000)
            await conn.execute(
                "UPDATE conversations SET current_leaf_id = ?, updated_at = ? WHERE id = ? AND space_id = ?",
                (message['id'], now, conv_id, space_id),
            )
            return True
    except Exception as e:
        print(f"Insert chat message error: {e}")
        return False


async def update_chat_message(message_id: str, updates: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """更新单条聊天消息（按空间校验，防误伤他人数据）。

    仅支持 ``content`` / ``timestamp`` 字段。用于「编辑最新提问」时改写 user 消息正文。
    """
    try:
        set_clauses: List[str] = []
        params: List[Any] = []
        if "content" in updates:
            set_clauses.append("content = ?")
            params.append(_encode_chat_content(updates["content"]))
        if "timestamp" in updates:
            set_clauses.append("timestamp = ?")
            params.append(updates["timestamp"])
        if not set_clauses:
            return True
        params.append(message_id)
        params.append(space_id)
        async with get_db() as conn:
            cur = await conn.execute(
                f"UPDATE chat_messages SET {', '.join(set_clauses)} WHERE id = ? AND space_id = ?",
                params,
            )
            return cur.rowcount > 0
    except Exception as e:
        print(f"Update chat message error: {e}")
        return False


async def delete_chat_messages_after(message_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    """删除某条消息之后的所有消息（按 timestamp 顺序尾部截断，幂等）。

    用于「重新生成」与「编辑最新提问」：锚定最后一条 user 消息，删掉其后的
    assistant 回复。截断后必须把会话的 current_leaf_id 指回锚点，否则当前分支
    会继续指向已删除的叶子，随后读取消息路径时将得到空列表。
    """
    try:
        async with get_db() as conn:
            row = await _fetchone(
                conn,
                "SELECT timestamp, conversation_id FROM chat_messages WHERE id = ? AND space_id = ?",
                (message_id, space_id),
            )
            if row:
                now = int(time.time() * 1000)
                await conn.execute(
                    "DELETE FROM chat_messages WHERE conversation_id = ? AND space_id = ? AND timestamp > ?",
                    (row["conversation_id"], space_id, row["timestamp"]),
                )
                await conn.execute(
                    "UPDATE conversations SET current_leaf_id = ?, updated_at = ? WHERE id = ? AND space_id = ?",
                    (message_id, now, row["conversation_id"], space_id),
                )
            return True
    except Exception as e:
        print(f"Delete chat messages after error: {e}")
        return False


async def get_conversation_messages(conversation_id: str, space_id: str = DEFAULT_SPACE) -> List[Dict[str, Any]]:
    """获取某空间对话当前分支的消息（从根到 current_leaf_id）。"""
    async with get_db() as conn:
        row = await _fetchone(
            conn,
            "SELECT current_leaf_id FROM conversations WHERE id = ? AND space_id = ?",
            (conversation_id, space_id),
        )
        if not row:
            return []
        leaf_id = row["current_leaf_id"] if "current_leaf_id" in row.keys() else None
        return await get_message_path(conn, conversation_id, leaf_id, space_id)


async def switch_conversation_leaf(conversation_id: str, leaf_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    """切换对话的当前分支到指定叶子消息（按空间校验）。

    用于前端「上一条/下一条分支」导航。leaf_id 必须属于该会话且在该空间内。
    """
    try:
        async with get_db() as conn:
            row = await _fetchone(
                conn,
                "SELECT id FROM chat_messages WHERE id = ? AND conversation_id = ? AND space_id = ?",
                (leaf_id, conversation_id, space_id),
            )
            if not row:
                return False
            now = int(time.time() * 1000)
            cur = await conn.execute(
                "UPDATE conversations SET current_leaf_id = ?, updated_at = ? WHERE id = ? AND space_id = ?",
                (leaf_id, now, conversation_id, space_id),
            )
            return cur.rowcount > 0
    except Exception as e:
        print(f"Switch conversation leaf error: {e}")
        return False


async def switch_to_message(conversation_id: str, message_id: str, space_id: str = DEFAULT_SPACE) -> Optional[str]:
    """切换分支到包含 message_id 的路径。

    message_id 可以是树中任意节点（不一定是叶子）。本函数沿子节点链向下走到
    最新叶子，然后把 current_leaf_id 设为该叶子并返回其 id。
    """
    try:
        async with get_db() as conn:
            # 确认消息存在且属于该会话/空间
            row = await _fetchone(
                conn,
                "SELECT id FROM chat_messages WHERE id = ? AND conversation_id = ? AND space_id = ?",
                (message_id, conversation_id, space_id),
            )
            if not row:
                return None
            # 向下找叶子：反复查 parent_id = 当前 id 的最新一条
            cur_id = message_id
            while True:
                child = await _fetchone(
                    conn,
                    "SELECT id FROM chat_messages WHERE conversation_id = ? AND space_id = ? AND parent_id = ? ORDER BY timestamp DESC LIMIT 1",
                    (conversation_id, space_id, cur_id),
                )
                if not child:
                    break
                cur_id = child["id"]
            now = int(time.time() * 1000)
            await conn.execute(
                "UPDATE conversations SET current_leaf_id = ?, updated_at = ? WHERE id = ? AND space_id = ?",
                (cur_id, now, conversation_id, space_id),
            )
            return cur_id
    except Exception as e:
        print(f"Switch to message error: {e}")
        return None


# ==================== 全局搜索 ====================

async def global_search(query: str, space_id: str = DEFAULT_SPACE, limit: int = 20) -> Dict[str, List[Dict[str, Any]]]:
    """某空间内的跨 Hub 全局搜索"""
    results = {
        'papers': [], 'tasks': [], 'projects': [], 'notes': [], 'experiments': [],
    }
    query_lower = query.lower()
    like = f'%{query_lower}%'
    async with get_db() as conn:
        rows = await _fetchall(
            conn,
            '''SELECT * FROM papers WHERE space_id = ? AND (LOWER(title) LIKE ? OR LOWER(abstract) LIKE ?)
               ORDER BY added_at DESC LIMIT ?''',
            (space_id, like, like, limit))
        results['papers'] = [paper_to_dict(r) for r in rows]

        rows = await _fetchall(
            conn,
            '''SELECT * FROM tasks WHERE space_id = ? AND (LOWER(title) LIKE ? OR LOWER(description) LIKE ?)
               ORDER BY created_at DESC LIMIT ?''',
            (space_id, like, like, limit))
        results['tasks'] = [task_to_dict(r) for r in rows]

        rows = await _fetchall(
            conn,
            '''SELECT * FROM software_projects WHERE space_id = ? AND (LOWER(name) LIKE ? OR LOWER(description) LIKE ?)
               ORDER BY created_at DESC LIMIT ?''',
            (space_id, like, like, limit))
        results['projects'] = [project_to_dict(r) for r in rows]

        rows = await _fetchall(
            conn,
            '''SELECT * FROM notes WHERE space_id = ? AND (LOWER(title) LIKE ? OR LOWER(content) LIKE ?)
               ORDER BY created_at DESC LIMIT ?''',
            (space_id, like, like, limit))
        results['notes'] = [note_to_dict(r) for r in rows]

        rows = await _fetchall(
            conn,
            '''SELECT * FROM experiments WHERE space_id = ? AND (LOWER(name) LIKE ? OR LOWER(description) LIKE ?)
               ORDER BY created_at DESC LIMIT ?''',
            (space_id, like, like, limit))
        results['experiments'] = [experiment_to_dict(r) for r in rows]

    return results


# ==================== Agent 会话管理（多 Agent 协作） ====================

def _session_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    """将 agent_sessions 行转换为前端契约所需的 camelCase 字典。"""
    return {
        'id': row['id'],
        'projectId': row['project_id'],
        'sessionType': row['session_type'],
        'status': row['status'],
        'progress': row['progress'],
        'currentStep': row['current_step'],
        'inputData': json.loads(row['input_data']) if row['input_data'] else None,
        'outputData': json.loads(row['output_data']) if row['output_data'] else None,
        'startedAt': row['started_at'],
        'completedAt': row['completed_at'],
        'errorMessage': row['error_message'],
    }


async def create_agent_session(project_id: Optional[str], session_type: str,
                               input_data: Any = None, status: str = 'running',
                               space_id: str = DEFAULT_SPACE) -> Dict[str, Any]:
    """创建一条 Agent 会话记录（按空间打标）并返回 camelCase 字典。"""
    try:
        now = int(time.time() * 1000)
        session_id = str(uuid.uuid4())
        async with get_db() as conn:
            await conn.execute('''
                INSERT INTO agent_sessions
                (id, project_id, session_type, status, input_data, progress, current_step, started_at, completed_at, space_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                session_id, project_id, session_type, status,
                json.dumps(input_data or {}, ensure_ascii=False), 0, '', now, None, space_id))
        return {
            'id': session_id, 'projectId': project_id, 'sessionType': session_type,
            'status': status, 'progress': 0, 'currentStep': '',
            'inputData': input_data, 'startedAt': now, 'completedAt': None,
        }
    except Exception as e:
        print(f"Create agent session error: {e}")
        return {}


async def get_agent_sessions(project_id: Optional[str] = None, space_id: str = DEFAULT_SPACE) -> List[Dict[str, Any]]:
    """列出某空间 Agent 会话（可按项目过滤）。"""
    async with get_db() as conn:
        if project_id:
            rows = await _fetchall(
                conn,
                'SELECT * FROM agent_sessions WHERE project_id = ? AND space_id = ? ORDER BY started_at DESC',
                (project_id, space_id))
        else:
            rows = await _fetchall(
                conn, 'SELECT * FROM agent_sessions WHERE space_id = ? ORDER BY started_at DESC', (space_id,))
        return [_session_to_dict(row) for row in rows]


async def get_agent_session(session_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """根据 id 获取单条 Agent 会话（按空间过滤）。"""
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT * FROM agent_sessions WHERE id = ? AND space_id = ?', (session_id, space_id))
        return _session_to_dict(row) if row else None


async def update_agent_session(session_id: str, updates: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """更新 Agent 会话（按空间校验）。"""
    allowed = {'status', 'progress', 'currentStep', 'outputData', 'completedAt', 'errorMessage'}
    updates = {k: v for k, v in updates.items() if k in allowed}
    if not updates:
        return False
    field_map = {
        'currentStep': 'current_step', 'outputData': 'output_data',
        'completedAt': 'completed_at', 'errorMessage': 'error_message',
    }
    set_clauses: List[str] = []
    values: List[Any] = []
    for key, value in updates.items():
        db_key = field_map.get(key, key)
        if key in ('outputData',):
            value = json.dumps(value, ensure_ascii=False)
        set_clauses.append(f"{db_key} = ?")
        values.append(value)
    values.append(session_id)
    values.append(space_id)
    try:
        async with get_db() as conn:
            cur = await conn.execute(
                f"UPDATE agent_sessions SET {', '.join(set_clauses)} WHERE id = ? AND space_id = ?", values)
        return cur.rowcount > 0
    except Exception as e:
        print(f"Update agent session error: {e}")
        return False


async def add_agent_message(session_id: str, event: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """将一条流式事件持久化为 agent_messages 行（按空间打标）。"""
    try:
        now = int(time.time() * 1000)
        msg_id = str(uuid.uuid4())
        agent_role = event.get('agent') or event.get('phase') or 'system'
        message_type = event.get('type') or 'output'
        content = event.get('message') or event.get('step') or ''
        step_name = event.get('step')
        metadata = {k: v for k, v in event.items()
                    if k not in ('agent', 'phase', 'type', 'message', 'step')}
        async with get_db() as conn:
            await conn.execute('''
                INSERT INTO agent_messages
                (id, session_id, agent_role, message_type, content, step_name, metadata, timestamp, space_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                msg_id, session_id, agent_role, message_type, content, step_name,
                json.dumps(metadata, ensure_ascii=False), now, space_id))
        return True
    except Exception as e:
        print(f"Add agent message error: {e}")
        return False


async def get_agent_messages(session_id: str, space_id: str = DEFAULT_SPACE) -> List[Dict[str, Any]]:
    """获取某空间会话的全部消息（流式事件回放）。"""
    async with get_db() as conn:
        rows = await _fetchall(
            conn,
            'SELECT * FROM agent_messages WHERE session_id = ? AND space_id = ? ORDER BY timestamp ASC',
            (session_id, space_id))
        return [{
            'id': row['id'],
            'sessionId': row['session_id'],
            'agentRole': row['agent_role'],
            'messageType': row['message_type'],
            'content': row['content'],
            'stepName': row['step_name'],
            'metadata': json.loads(row['metadata']) if row['metadata'] else {},
            'timestamp': row['timestamp'],
        } for row in rows]


# ==================== Agent teams and role templates ====================

def _team_record_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    definition = json.loads(row['definition']) if row['definition'] else {}
    return {
        **definition,
        'id': row['id'],
        'name': row['name'],
        'description': row['description'] or '',
        'category': row['category'] or 'custom',
        'builtin': False,
        'createdAt': row['created_at'],
        'updatedAt': row['updated_at'],
    }


async def list_agent_teams(space_id: str = DEFAULT_SPACE) -> List[Dict[str, Any]]:
    async with get_db() as conn:
        rows = await _fetchall(
            conn, 'SELECT * FROM agent_teams WHERE space_id = ? ORDER BY updated_at DESC',
            (space_id,))
        return [_team_record_to_dict(row) for row in rows]


async def get_agent_team(team_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    async with get_db() as conn:
        row = await _fetchone(
            conn, 'SELECT * FROM agent_teams WHERE id = ? AND space_id = ?',
            (team_id, space_id))
        return _team_record_to_dict(row) if row else None


async def create_agent_team(definition: Dict[str, Any], space_id: str = DEFAULT_SPACE,
                            team_id: Optional[str] = None) -> Dict[str, Any]:
    now = int(time.time() * 1000)
    team_id = team_id or str(uuid.uuid4())
    payload = {key: value for key, value in definition.items()
               if key not in {'id', 'builtin', 'createdAt', 'updatedAt'}}
    async with get_db() as conn:
        await conn.execute('''
            INSERT INTO agent_teams
            (id, space_id, name, description, category, definition, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (team_id, space_id, payload.get('name', ''), payload.get('description', ''),
              payload.get('category', 'custom'), json.dumps(payload, ensure_ascii=False), now, now))
    return await get_agent_team(team_id, space_id) or {}


async def update_agent_team(team_id: str, definition: Dict[str, Any],
                            space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    payload = {key: value for key, value in definition.items()
               if key not in {'id', 'builtin', 'createdAt', 'updatedAt'}}
    async with get_db() as conn:
        cur = await conn.execute('''
            UPDATE agent_teams SET name = ?, description = ?, category = ?,
                definition = ?, updated_at = ? WHERE id = ? AND space_id = ?
        ''', (payload.get('name', ''), payload.get('description', ''), payload.get('category', 'custom'),
              json.dumps(payload, ensure_ascii=False), int(time.time() * 1000), team_id, space_id))
        if cur.rowcount <= 0:
            return None
    return await get_agent_team(team_id, space_id)


async def delete_agent_team(team_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    async with get_db() as conn:
        cur = await conn.execute(
            'DELETE FROM agent_teams WHERE id = ? AND space_id = ?', (team_id, space_id))
        return cur.rowcount > 0


def _role_template_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    definition = json.loads(row['definition']) if row['definition'] else {}
    return {
        **definition, 'id': row['id'], 'name': row['name'],
        'description': row['description'] or '', 'builtin': False,
        'createdAt': row['created_at'], 'updatedAt': row['updated_at'],
    }


async def list_agent_role_templates(space_id: str = DEFAULT_SPACE) -> List[Dict[str, Any]]:
    async with get_db() as conn:
        rows = await _fetchall(
            conn, 'SELECT * FROM agent_role_templates WHERE space_id = ? ORDER BY updated_at DESC',
            (space_id,))
        return [_role_template_to_dict(row) for row in rows]


async def get_agent_role_template(template_id: str,
                                  space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    async with get_db() as conn:
        row = await _fetchone(conn,
            'SELECT * FROM agent_role_templates WHERE id = ? AND space_id = ?',
            (template_id, space_id))
        return _role_template_to_dict(row) if row else None


async def create_agent_role_template(definition: Dict[str, Any], space_id: str = DEFAULT_SPACE,
                                     template_id: Optional[str] = None) -> Dict[str, Any]:
    now = int(time.time() * 1000)
    template_id = template_id or str(uuid.uuid4())
    payload = {key: value for key, value in definition.items()
               if key not in {'id', 'builtin', 'createdAt', 'updatedAt'}}
    async with get_db() as conn:
        await conn.execute('''
            INSERT INTO agent_role_templates
            (id, space_id, name, description, definition, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (template_id, space_id, payload.get('name', ''), payload.get('description', ''),
              json.dumps(payload, ensure_ascii=False), now, now))
    return await get_agent_role_template(template_id, space_id) or {}


async def update_agent_role_template(template_id: str, definition: Dict[str, Any],
                                     space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    payload = {key: value for key, value in definition.items()
               if key not in {'id', 'builtin', 'createdAt', 'updatedAt'}}
    async with get_db() as conn:
        cur = await conn.execute('''
            UPDATE agent_role_templates SET name = ?, description = ?, definition = ?, updated_at = ?
            WHERE id = ? AND space_id = ?
        ''', (payload.get('name', ''), payload.get('description', ''),
              json.dumps(payload, ensure_ascii=False), int(time.time() * 1000), template_id, space_id))
        if cur.rowcount <= 0:
            return None
    return await get_agent_role_template(template_id, space_id)


async def delete_agent_role_template(template_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    async with get_db() as conn:
        cur = await conn.execute(
            'DELETE FROM agent_role_templates WHERE id = ? AND space_id = ?',
            (template_id, space_id))
        return cur.rowcount > 0


# ==================== Agent 后台运行（非阻塞 runner，按空间隔离） ====================

def _run_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    """将 agent_runs 行转换为前端契约的 camelCase 字典。"""
    if not row:
        return {}
    keys = set(row.keys())
    def parsed(column: str) -> Any:
        return json.loads(row[column]) if column in keys and row[column] else None
    return {
        'id': row['id'],
        'spaceId': row['space_id'],
        'projectId': row['project_id'],
        'requirement': row['requirement'],
        'roles': json.loads(row['roles']) if row['roles'] else [],
        'teamId': row['team_id'],
        'teamName': row['team_name'],
        'teamSnapshot': json.loads(row['team_snapshot']) if row['team_snapshot'] else None,
        'inputContext': json.loads(row['input_context']) if row['input_context'] else None,
        'status': row['status'],
        'errorMessage': row['error_message'],
        'resultSummary': json.loads(row['result_summary']) if row['result_summary'] else None,
        'createdAt': row['created_at'],
        'startedAt': row['started_at'],
        'completedAt': row['completed_at'],
        'runKind': row['run_kind'] if 'run_kind' in keys else 'dag',
        'phase': row['phase'] if 'phase' in keys else None,
        'iteration': row['iteration'] if 'iteration' in keys else 0,
        'maxIterations': row['max_iterations'] if 'max_iterations' in keys else None,
        'deadlineAt': row['deadline_at'] if 'deadline_at' in keys else None,
        'workspaceSnapshot': parsed('workspace_snapshot'),
        'checkpoint': parsed('checkpoint'),
        'authorization': parsed('authorization'),
        'budgetUsedMs': row['budget_used_ms'] if 'budget_used_ms' in keys else 0,
    }


async def create_agent_run(run_id: str, space_id: str, project_id: Optional[str],
                           requirement: str, roles: Any = None, status: str = 'running',
                           team_id: Optional[str] = None, team_name: Optional[str] = None,
                           team_snapshot: Any = None, input_context: Any = None,
                           run_kind: str = 'dag', phase: Optional[str] = None,
                           max_iterations: Optional[int] = None,
                           deadline_at: Optional[int] = None,
                           workspace_snapshot: Any = None, checkpoint: Any = None,
                           authorization: Any = None) -> str:
    """创建一条后台 Agent 运行记录（按空间打标）并返回 run id。"""
    try:
        now = int(time.time() * 1000)
        async with get_db() as conn:
            await conn.execute('''
                INSERT INTO agent_runs
                (id, space_id, project_id, requirement, roles, status, created_at, started_at,
                 completed_at, team_id, team_name, team_snapshot, input_context,
                 run_kind, phase, max_iterations, deadline_at, workspace_snapshot,
                 checkpoint, authorization)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                run_id, space_id, project_id, requirement,
                json.dumps(roles or [], ensure_ascii=False), status, now, None, None,
                team_id, team_name,
                json.dumps(team_snapshot, ensure_ascii=False) if team_snapshot is not None else None,
                json.dumps(input_context, ensure_ascii=False) if input_context is not None else None,
                run_kind, phase, max_iterations, deadline_at,
                json.dumps(workspace_snapshot, ensure_ascii=False) if workspace_snapshot is not None else None,
                json.dumps(checkpoint, ensure_ascii=False) if checkpoint is not None else None,
                json.dumps(authorization, ensure_ascii=False) if authorization is not None else None))
        return run_id
    except Exception as e:
        print(f"Create agent run error: {e}")
        return ""


async def update_agent_run(run_id: str, space_id: str, status: Optional[str] = None,
                           error_message: Optional[str] = None,
                           result_summary: Any = None,
                           started_at: Optional[int] = None,
                           completed_at: Optional[int] = None,
                           phase: Optional[str] = None,
                           iteration: Optional[int] = None,
                           max_iterations: Optional[int] = None,
                           deadline_at: Optional[int] = None,
                           workspace_snapshot: Any = None,
                           checkpoint: Any = None,
                           authorization: Any = None,
                           budget_used_ms: Optional[int] = None,
                           lease_owner: Optional[str] = None,
                           lease_expires_at: Optional[int] = None) -> bool:
    """更新一条后台运行记录（按空间校验）。仅接受白名单字段。"""
    allowed = {
        'status', 'error_message', 'result_summary', 'started_at', 'completed_at',
        'phase', 'iteration', 'max_iterations', 'deadline_at', 'workspace_snapshot',
        'checkpoint', 'authorization', 'budget_used_ms', 'lease_owner', 'lease_expires_at',
    }
    updates = {
        'status': status, 'error_message': error_message,
        'result_summary': result_summary, 'started_at': started_at,
        'completed_at': completed_at, 'phase': phase, 'iteration': iteration,
        'max_iterations': max_iterations, 'deadline_at': deadline_at,
        'workspace_snapshot': workspace_snapshot, 'checkpoint': checkpoint,
        'authorization': authorization, 'budget_used_ms': budget_used_ms,
        'lease_owner': lease_owner, 'lease_expires_at': lease_expires_at,
    }
    updates = {k: v for k, v in updates.items() if v is not None and k in allowed}
    if not updates:
        return False
    set_clauses: List[str] = []
    values: List[Any] = []
    for key, value in updates.items():
        if key in {'result_summary', 'workspace_snapshot', 'checkpoint', 'authorization'}:
            value = json.dumps(value, ensure_ascii=False)
        set_clauses.append(f"{key} = ?")
        values.append(value)
    values.append(run_id)
    values.append(space_id)
    try:
        async with get_db() as conn:
            cur = await conn.execute(
                f"UPDATE agent_runs SET {', '.join(set_clauses)} WHERE id = ? AND space_id = ?", values)
        return cur.rowcount > 0
    except Exception as e:
        print(f"Update agent run error: {e}")
        return False


async def get_agent_run(run_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """根据 id 获取单条运行记录（按空间过滤）。"""
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT * FROM agent_runs WHERE id = ? AND space_id = ?', (run_id, space_id))
        return _run_to_dict(row) if row else None


async def get_agent_run_status(run_id: str, space_id: str = DEFAULT_SPACE) -> Optional[str]:
    """仅取运行状态（供后台线程跨 worker 轮询取消标志）。"""
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT status FROM agent_runs WHERE id = ? AND space_id = ?', (run_id, space_id))
        return row['status'] if row else None


async def add_agent_run_event(run_id: str, space_id: str, event: Dict[str, Any]) -> bool:
    """将一条运行事件持久化为 agent_run_events 行（按空间打标）。返回自增 id 由调用方无关。"""
    try:
        now = int(time.time() * 1000)
        event_type = event.get('type') or event.get('agent') or 'event'
        async with get_db() as conn:
            await conn.execute('''
                INSERT INTO agent_run_events (run_id, space_id, type, data, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (run_id, space_id, event_type, json.dumps(event, ensure_ascii=False), now))
        return True
    except Exception as e:
        print(f"Add agent run event error: {e}")
        return False


async def finish_agent_run(run_id: str, space_id: str, status: str,
                           event: Dict[str, Any], result_summary: Any = None,
                           error_message: Optional[str] = None) -> bool:
    """Atomically transition a live run and append exactly one terminal event.

    The guarded UPDATE prevents a late worker result from reviving a run after
    another worker (or the user) has cancelled it.
    """
    if status not in {'completed', 'failed'}:
        raise ValueError("finish_agent_run status must be completed or failed")
    now = int(time.time() * 1000)
    summary_json = (json.dumps(result_summary, ensure_ascii=False)
                    if result_summary is not None else None)
    async with get_db() as conn:
        cur = await conn.execute('''
            UPDATE agent_runs SET status = ?, result_summary = COALESCE(?, result_summary),
                error_message = ?, completed_at = ?
            WHERE id = ? AND space_id = ? AND status IN ('pending', 'running')
        ''', (status, summary_json, error_message, now, run_id, space_id))
        if cur.rowcount <= 0:
            return False
        event_type = event.get('type') or status
        await conn.execute('''
            INSERT INTO agent_run_events (run_id, space_id, type, data, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (run_id, space_id, event_type, json.dumps(event, ensure_ascii=False), now))
        return True


async def get_agent_run_events(run_id: str, space_id: str = DEFAULT_SPACE,
                               after_id: int = 0) -> List[Dict[str, Any]]:
    """获取某运行、某空间的全部（或 after_id 之后的增量）事件，按 id 升序。"""
    async with get_db() as conn:
        rows = await _fetchall(
            conn,
            'SELECT * FROM agent_run_events WHERE run_id = ? AND space_id = ? AND id > ? ORDER BY id ASC',
            (run_id, space_id, after_id))
        return [{
            'id': row['id'],
            'runId': row['run_id'],
            'type': row['type'],
            'data': json.loads(row['data']) if row['data'] else {},
            'createdAt': row['created_at'],
        } for row in rows]


async def list_agent_runs(space_id: str = DEFAULT_SPACE, project_id: Optional[str] = None,
                          limit: int = 50) -> List[Dict[str, Any]]:
    """列出某空间的后台运行（可按项目过滤），按创建时间倒序。"""
    async with get_db() as conn:
        if project_id:
            rows = await _fetchall(
                conn,
                'SELECT * FROM agent_runs WHERE project_id = ? AND space_id = ? ORDER BY created_at DESC LIMIT ?',
                (project_id, space_id, limit))
        else:
            rows = await _fetchall(
                conn, 'SELECT * FROM agent_runs WHERE space_id = ? ORDER BY created_at DESC LIMIT ?',
                (space_id, limit))
        return [_run_to_dict(row) for row in rows]


async def cancel_agent_run(run_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    """Atomically mark a live run cancelled and append its terminal event."""
    async with get_db() as conn:
        now = int(time.time() * 1000)
        cur = await conn.execute(
            "UPDATE agent_runs SET status = 'cancelled', completed_at = ? "
            "WHERE id = ? AND space_id = ? AND status IN ('pending', 'running')",
            (now, run_id, space_id))
        if cur.rowcount <= 0:
            return False
        event = {"type": "run_cancelled", "message": "Run cancelled"}
        await conn.execute('''
            INSERT INTO agent_run_events (run_id, space_id, type, data, created_at)
            VALUES (?, ?, 'run_cancelled', ?, ?)
        ''', (run_id, space_id, json.dumps(event, ensure_ascii=False), now))
        return True


# ==================== 持久化研发运行 ====================

async def claim_development_run(run_id: str, space_id: str, owner: str,
                                lease_ms: int = 30000) -> bool:
    """原子领取一条待执行/租约过期的研发运行。"""
    now = int(time.time() * 1000)
    async with get_db() as conn:
        cur = await conn.execute('''
            UPDATE agent_runs SET lease_owner = ?, lease_expires_at = ?, status = 'running',
                started_at = COALESCE(started_at, ?)
            WHERE id = ? AND space_id = ? AND run_kind = 'development'
              AND status IN ('pending', 'running')
              AND (lease_owner IS NULL OR lease_owner = ? OR lease_expires_at IS NULL OR lease_expires_at < ?)
        ''', (owner, now + lease_ms, now, run_id, space_id, owner, now))
        return cur.rowcount > 0


async def renew_development_lease(run_id: str, space_id: str, owner: str,
                                  lease_ms: int = 30000) -> bool:
    now = int(time.time() * 1000)
    async with get_db() as conn:
        cur = await conn.execute('''
            UPDATE agent_runs SET lease_expires_at = ?
            WHERE id = ? AND space_id = ? AND run_kind = 'development'
              AND status = 'running' AND lease_owner = ?
        ''', (now + lease_ms, run_id, space_id, owner))
        return cur.rowcount > 0


async def finish_development_run(run_id: str, space_id: str, owner: str,
                                 status: str, phase: str,
                                 result_summary: Any = None,
                                 error_message: Optional[str] = None) -> bool:
    now = int(time.time() * 1000)
    async with get_db() as conn:
        cur = await conn.execute('''
            UPDATE agent_runs SET status = ?, phase = ?, result_summary = COALESCE(?, result_summary),
                error_message = ?, completed_at = ?, lease_owner = NULL, lease_expires_at = NULL
            WHERE id = ? AND space_id = ? AND run_kind = 'development' AND lease_owner = ?
              AND status = 'running'
        ''', (status, phase,
              json.dumps(result_summary, ensure_ascii=False) if result_summary is not None else None,
              error_message, now, run_id, space_id, owner))
        if cur.rowcount <= 0:
            return False
        event = {"type": "run_complete" if status == "completed" else "run_failed",
                 "phase": phase, "message": error_message or phase}
        await conn.execute('''
            INSERT INTO agent_run_events (run_id, space_id, type, data, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (run_id, space_id, event["type"], json.dumps(event, ensure_ascii=False), now))
        return True


async def continue_development_run(run_id: str, space_id: str,
                                   additional_iterations: int,
                                   additional_minutes: int,
                                   feedback: Optional[str] = None) -> bool:
    now = int(time.time() * 1000)
    async with get_db() as conn:
        row = await _fetchone(conn, '''
            SELECT max_iterations, deadline_at, checkpoint FROM agent_runs
            WHERE id = ? AND space_id = ? AND run_kind = 'development'
              AND status = 'failed' AND phase = 'budget_exhausted'
        ''', (run_id, space_id))
        if not row:
            return False
        checkpoint = json.loads(row['checkpoint']) if row['checkpoint'] else {}
        if feedback:
            previous = checkpoint.get('feedback') or ''
            checkpoint['feedback'] = (f"{previous}\n\n用户追加反馈：{feedback}" if previous else
                                      f"用户追加反馈：{feedback}")[-40000:]
        cur = await conn.execute('''
            UPDATE agent_runs SET status = 'pending', phase = 'queued', completed_at = NULL,
                error_message = NULL, max_iterations = ?, deadline_at = ?, checkpoint = ?,
                lease_owner = NULL, lease_expires_at = NULL
            WHERE id = ? AND space_id = ?
        ''', ((row['max_iterations'] or 0) + additional_iterations,
              max(now, row['deadline_at'] or now) + additional_minutes * 60 * 1000,
              json.dumps(checkpoint, ensure_ascii=False), run_id, space_id))
        return cur.rowcount > 0


async def list_claimable_development_runs(limit: int = 20) -> List[Dict[str, Any]]:
    now = int(time.time() * 1000)
    async with get_db() as conn:
        rows = await _fetchall(conn, '''
            SELECT * FROM agent_runs WHERE run_kind = 'development'
              AND status IN ('pending', 'running')
              AND (lease_owner IS NULL OR lease_expires_at IS NULL OR lease_expires_at < ?)
            ORDER BY created_at ASC LIMIT ?
        ''', (now, limit))
        return [_run_to_dict(row) for row in rows]


async def create_development_step(run_id: str, space_id: str, iteration: int,
                                  phase: str, stage_node_id: Optional[str] = None,
                                  input_summary: Optional[str] = None,
                                  attempt: int = 1) -> str:
    step_id = str(uuid.uuid4())
    now = int(time.time() * 1000)
    async with get_db() as conn:
        await conn.execute('''
            INSERT OR REPLACE INTO development_run_steps
            (id, run_id, space_id, iteration, phase, stage_node_id, attempt, status,
             input_summary, started_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?, ?)
        ''', (step_id, run_id, space_id, iteration, phase, stage_node_id,
              attempt, _clean_text_for_db(input_summary), now))
    return step_id


async def finish_development_step(step_id: str, run_id: str, space_id: str,
                                  status: str, output: Any = None,
                                  error_message: Optional[str] = None) -> bool:
    now = int(time.time() * 1000)
    output_text = (json.dumps(output, ensure_ascii=False)
                   if output is not None and not isinstance(output, str) else output)
    async with get_db() as conn:
        cur = await conn.execute('''
            UPDATE development_run_steps SET status = ?, output = ?, error_message = ?, completed_at = ?
            WHERE id = ? AND run_id = ? AND space_id = ?
        ''', (status, _clean_text_for_db(output_text), _clean_text_for_db(error_message),
              now, step_id, run_id, space_id))
        return cur.rowcount > 0


def _development_step_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    output: Any = row['output']
    if output:
        try:
            output = json.loads(output)
        except json.JSONDecodeError:
            pass
    return {
        'id': row['id'], 'runId': row['run_id'], 'iteration': row['iteration'],
        'phase': row['phase'], 'stageNodeId': row['stage_node_id'],
        'attempt': row['attempt'], 'status': row['status'],
        'inputSummary': row['input_summary'], 'output': output,
        'errorMessage': row['error_message'], 'startedAt': row['started_at'],
        'completedAt': row['completed_at'],
    }


async def list_development_steps(run_id: str, space_id: str) -> List[Dict[str, Any]]:
    async with get_db() as conn:
        rows = await _fetchall(conn, '''
            SELECT * FROM development_run_steps WHERE run_id = ? AND space_id = ?
            ORDER BY iteration ASC, started_at ASC
        ''', (run_id, space_id))
        return [_development_step_to_dict(row) for row in rows]


async def add_development_artifact(run_id: str, space_id: str, iteration: int,
                                   kind: str, content: Optional[str] = None,
                                   relative_path: Optional[str] = None,
                                   metadata: Any = None) -> str:
    artifact_id = str(uuid.uuid4())
    async with get_db() as conn:
        await conn.execute('''
            INSERT INTO development_artifacts
            (id, run_id, space_id, iteration, kind, relative_path, content, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (artifact_id, run_id, space_id, iteration, kind, relative_path,
              _clean_text_for_db(content[:262144] if content else None),
              json.dumps(metadata, ensure_ascii=False) if metadata is not None else None,
              int(time.time() * 1000)))
    return artifact_id


async def list_development_artifacts(run_id: str, space_id: str) -> List[Dict[str, Any]]:
    async with get_db() as conn:
        rows = await _fetchall(conn, '''
            SELECT * FROM development_artifacts WHERE run_id = ? AND space_id = ?
            ORDER BY created_at ASC
        ''', (run_id, space_id))
        return [{
            'id': row['id'], 'runId': row['run_id'], 'iteration': row['iteration'],
            'kind': row['kind'], 'relativePath': row['relative_path'],
            'content': row['content'],
            'metadata': json.loads(row['metadata']) if row['metadata'] else None,
            'createdAt': row['created_at'],
        } for row in rows]


def _run_node_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    return {
        'runId': row['run_id'], 'nodeId': row['node_id'], 'name': row['node_name'],
        'status': row['status'], 'textOutput': row['text_output'],
        'structuredOutput': json.loads(row['structured_output']) if row['structured_output'] else None,
        'errorMessage': row['error_message'], 'queuedAt': row['queued_at'],
        'startedAt': row['started_at'], 'completedAt': row['completed_at'],
    }


async def create_agent_run_nodes(run_id: str, space_id: str,
                                 nodes: List[Dict[str, Any]]) -> None:
    now = int(time.time() * 1000)
    async with get_db() as conn:
        for node in nodes:
            await conn.execute('''
                INSERT OR IGNORE INTO agent_run_nodes
                (run_id, node_id, space_id, node_name, status, queued_at)
                VALUES (?, ?, ?, ?, 'pending', ?)
            ''', (run_id, node['id'], space_id, node.get('name', node['id']), now))


async def update_agent_run_node(run_id: str, node_id: str, space_id: str,
                                status: Optional[str] = None, text_output: Optional[str] = None,
                                structured_output: Any = None, error_message: Optional[str] = None,
                                started_at: Optional[int] = None,
                                completed_at: Optional[int] = None) -> bool:
    values_by_column = {
        'status': status, 'text_output': text_output,
        'structured_output': (json.dumps(structured_output, ensure_ascii=False)
                              if structured_output is not None else None),
        'error_message': error_message, 'started_at': started_at, 'completed_at': completed_at,
    }
    updates = {key: value for key, value in values_by_column.items() if value is not None}
    if not updates:
        return False
    assignments = ', '.join(f'{column} = ?' for column in updates)
    async with get_db() as conn:
        cur = await conn.execute(
            f'UPDATE agent_run_nodes SET {assignments} WHERE run_id = ? AND node_id = ? AND space_id = ?',
            (*updates.values(), run_id, node_id, space_id))
        return cur.rowcount > 0


async def list_agent_run_nodes(run_id: str,
                               space_id: str = DEFAULT_SPACE) -> List[Dict[str, Any]]:
    async with get_db() as conn:
        rows = await _fetchall(conn, '''
            SELECT * FROM agent_run_nodes WHERE run_id = ? AND space_id = ?
            ORDER BY queued_at ASC, node_id ASC
        ''', (run_id, space_id))
        return [_run_node_to_dict(row) for row in rows]


async def cancel_pending_agent_run_nodes(run_id: str, space_id: str,
                                         status: str = 'cancelled') -> None:
    async with get_db() as conn:
        await conn.execute('''
            UPDATE agent_run_nodes SET status = ?, completed_at = ?
            WHERE run_id = ? AND space_id = ? AND status IN ('pending', 'ready')
        ''', (status, int(time.time() * 1000), run_id, space_id))


# ==================== Agent 工具审批（P0，按空间隔离） ====================

def _approval_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    return {
        'id': row['id'],
        'runId': row['run_id'],
        'spaceId': row['space_id'],
        'tool': row['tool'],
        'nodeId': row['node_id'],
        'parameters': json.loads(row['parameters']) if row['parameters'] else {},
        'status': row['status'],
        'createdAt': row['created_at'],
        'decidedAt': row['decided_at'],
    }


async def create_agent_tool_approval(approval_id: str, run_id: str, space_id: str,
                                     tool: str, parameters: Any,
                                     node_id: Optional[str] = None) -> bool:
    """落一条 pending 审批记录，返回是否成功。"""
    try:
        now = int(time.time() * 1000)
        async with get_db() as conn:
            await conn.execute('''
                INSERT INTO agent_tool_approvals
                (id, run_id, space_id, tool, node_id, parameters, status, created_at, decided_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, NULL)
            ''', (approval_id, run_id, space_id, tool, node_id,
                  json.dumps(parameters, ensure_ascii=False), now))
        return True
    except Exception as e:
        print(f"Create agent tool approval error: {e}")
        return False


async def get_agent_tool_approval(approval_id: str, run_id: str,
                                  space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """按 id + 空间取一条审批记录（供 runner 轮询决策）。"""
    async with get_db() as conn:
        row = await _fetchone(
            conn,
            'SELECT * FROM agent_tool_approvals WHERE id = ? AND run_id = ? AND space_id = ?',
            (approval_id, run_id, space_id))
        return _approval_to_dict(row) if row else None


async def decide_agent_tool_approval(approval_id: str, run_id: str, space_id: str,
                                     approved: Optional[bool] = None,
                                     status: Optional[str] = None) -> bool:
    """对 pending 审批做决策：approved=True -> 'approved'，False -> 'denied'，
    或直接指定终态 status（'timed_out' / 'cancelled'）。仅 pending 时生效。"""
    if status is None:
        status = 'approved' if approved else 'denied'
    async with get_db() as conn:
        cur = await conn.execute(
            "UPDATE agent_tool_approvals SET status = ?, decided_at = ? "
            "WHERE id = ? AND run_id = ? AND space_id = ? AND status = 'pending'",
            (status, int(time.time() * 1000), approval_id, run_id, space_id))
        return cur.rowcount > 0


async def list_agent_tool_approvals(run_id: str, space_id: str = DEFAULT_SPACE,
                                    status: Optional[str] = None) -> List[Dict[str, Any]]:
    """列出某运行的全部（或指定状态）审批记录，按创建时间升序。"""
    async with get_db() as conn:
        if status:
            rows = await _fetchall(
                conn,
                'SELECT * FROM agent_tool_approvals WHERE run_id = ? AND space_id = ? AND status = ? ORDER BY created_at ASC',
                (run_id, space_id, status))
        else:
            rows = await _fetchall(
                conn,
                'SELECT * FROM agent_tool_approvals WHERE run_id = ? AND space_id = ? ORDER BY created_at ASC',
                (run_id, space_id))
        return [_approval_to_dict(row) for row in rows]


# ==================== Agent 可重放消息（P1，按空间隔离） ====================

async def append_agent_replay(run_id: str, space_id: str, phase: str, round_: int,
                              messages: List[Dict[str, Any]]) -> bool:
    """把某一轮「模型实际看到的消息序列」逐条落库（含 tool_calls 结构）。"""
    try:
        now = int(time.time() * 1000)
        async with get_db() as conn:
            for m in messages:
                await conn.execute('''
                    INSERT INTO agent_replay_messages (run_id, space_id, phase, round, role, content, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (run_id, space_id, phase, round_, m.get('role', 'user'),
                      json.dumps(m, ensure_ascii=False), now))
        return True
    except Exception as e:
        print(f"Append agent replay error: {e}")
        return False


async def get_agent_replay(run_id: str, space_id: str = DEFAULT_SPACE) -> List[Dict[str, Any]]:
    """按 (phase, round, id) 顺序取回完整重放消息，供前端会话回放。"""
    async with get_db() as conn:
        rows = await _fetchall(
            conn,
            'SELECT * FROM agent_replay_messages WHERE run_id = ? AND space_id = ? '
            'ORDER BY phase, round ASC, id ASC',
            (run_id, space_id))
        return [{
            'id': row['id'],
            'runId': row['run_id'],
            'phase': row['phase'],
            'round': row['round'],
            'role': row['role'],
            'message': json.loads(row['content']) if row['content'] else {},
            'createdAt': row['created_at'],
        } for row in rows]


# ==================== Cron 任务（DB 存储，按空间隔离） ====================

def cron_job_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    """将 cron_jobs 行转换为前端契约的 camelCase 字典。"""
    return {
        'id': row['id'],
        'name': row['name'],
        'description': row['description'],
        'schedule': row['schedule'],
        'command': row['command'],
        'jobType': row['job_type'],
        'payload': json.loads(row['payload']) if row['payload'] else None,
        'enabled': bool(row['enabled']),
        'lastRun': row['last_run'],
        'nextRun': row['next_run'],
        'runCount': row['run_count'],
        'createdAt': row['created_at'],
    }


async def get_cron_jobs(space_id: str = DEFAULT_SPACE) -> List[Dict[str, Any]]:
    """获取某空间的定时任务列表。"""
    async with get_db() as conn:
        rows = await _fetchall(
            conn, 'SELECT * FROM cron_jobs WHERE space_id = ? ORDER BY created_at DESC', (space_id,))
        return [cron_job_to_dict(row) for row in rows]


async def create_cron_job(job: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> Dict[str, Any]:
    """在某空间创建定时任务。"""
    now = int(time.time() * 1000)
    job_id = job.get('id') or str(uuid.uuid4())
    job_type = job.get('jobType') or job.get('job_type') or 'command'
    payload = job.get('payload')
    payload_str = json.dumps(payload, ensure_ascii=False) if payload else None
    record = {
        'id': job_id,
        'name': job.get('name', ''),
        'description': job.get('description', ''),
        'schedule': job.get('schedule', ''),
        'command': job.get('command', ''),
        'jobType': job_type,
        'payload': payload,
        'enabled': bool(job.get('enabled', True)),
        'lastRun': None,
        'nextRun': None,
        'runCount': 0,
        'createdAt': job.get('createdAt', now),
    }
    try:
        async with get_db() as conn:
            await conn.execute('''
                INSERT INTO cron_jobs
                (id, name, description, schedule, command, job_type, payload, enabled, last_run, next_run, run_count, created_at, space_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                record['id'], record['name'], record['description'], record['schedule'], record['command'],
                job_type, payload_str,
                1 if record['enabled'] else 0, record['lastRun'], record['nextRun'], record['runCount'],
                record['createdAt'], space_id))
        return record
    except Exception as e:
        print(f"Create cron job error: {e}")
        return {}


async def toggle_cron_job(job_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """切换某空间任务启用状态，返回更新后的任务；不存在返回 None。"""
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT * FROM cron_jobs WHERE id = ? AND space_id = ?', (job_id, space_id))
        if not row:
            return None
        new_enabled = 0 if row['enabled'] else 1
        await conn.execute('UPDATE cron_jobs SET enabled = ? WHERE id = ? AND space_id = ?',
                           (new_enabled, job_id, space_id))
        row = await _fetchone(conn, 'SELECT * FROM cron_jobs WHERE id = ? AND space_id = ?', (job_id, space_id))
        return cron_job_to_dict(row)


async def run_cron_job(job_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """标记某空间任务已运行（更新 lastRun / runCount），返回更新后的任务；不存在返回 None。"""
    now = int(time.time() * 1000)
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT * FROM cron_jobs WHERE id = ? AND space_id = ?', (job_id, space_id))
        if not row:
            return None
        await conn.execute(
            'UPDATE cron_jobs SET last_run = ?, run_count = run_count + 1 WHERE id = ? AND space_id = ?',
            (now, job_id, space_id))
        row = await _fetchone(conn, 'SELECT * FROM cron_jobs WHERE id = ? AND space_id = ?', (job_id, space_id))
        return cron_job_to_dict(row)


async def delete_cron_job(job_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    """删除某空间定时任务。"""
    try:
        async with get_db() as conn:
            cur = await conn.execute('DELETE FROM cron_jobs WHERE id = ? AND space_id = ?', (job_id, space_id))
            return cur.rowcount > 0
    except Exception as e:
        print(f"Delete cron job error: {e}")
        return False


# ==================== Cron 调度器支持（多 Worker 安全） ====================

async def get_due_cron_jobs(now_ms: int) -> List[Dict[str, Any]]:
    """获取所有已到点、已启用且 next_run <= now 的任务（跨所有空间）。

    调度器每轮调用此函数扫描到期任务，再对每个任务做原子抢锁。
    """
    async with get_db() as conn:
        rows = await _fetchall(
            conn,
            'SELECT * FROM cron_jobs WHERE enabled = 1 AND next_run IS NOT NULL AND next_run <= ?',
            (now_ms,))
        return [dict(row) for row in rows]


async def try_acquire_cron_job(
    job_id: str,
    space_id: str,
    expected_next_run_ms: int,
    now_ms: int,
    following_next_run_ms: int,
) -> bool:
    """Atomically claim one due schedule occurrence and advance its cursor.

    ``expected_next_run_ms`` acts as the optimistic-lock token.  Updating the
    cursor in the same statement means a worker holding a stale due-job snapshot
    cannot claim the same occurrence after another worker has rescheduled it.
    """
    async with get_db() as conn:
        cur = await conn.execute(
            'UPDATE cron_jobs '
            'SET last_run = ?, next_run = ?, run_count = run_count + 1 '
            'WHERE id = ? AND space_id = ? AND enabled = 1 '
            'AND next_run = ? AND next_run <= ?',
            (
                now_ms, following_next_run_ms, job_id, space_id,
                expected_next_run_ms, now_ms,
            ),
        )
        return cur.rowcount > 0


async def update_cron_next_run(job_id: str, next_run_ms: int) -> None:
    """更新任务下次执行时间（调度器在抢锁成功后调用）。"""
    async with get_db() as conn:
        await conn.execute(
            'UPDATE cron_jobs SET next_run = ?, run_count = run_count + 1 WHERE id = ?',
            (next_run_ms, job_id))


async def init_cron_next_run(job_id: str, next_run_ms: int) -> None:
    """初始化任务的 next_run（创建或启用时调用）。"""
    async with get_db() as conn:
        await conn.execute(
            'UPDATE cron_jobs SET next_run = ? WHERE id = ?', (next_run_ms, job_id))


async def get_all_cron_jobs() -> List[Dict[str, Any]]:
    """获取所有空间的定时任务（调度器初始化时用，计算 next_run）。"""
    async with get_db() as conn:
        rows = await _fetchall(
            conn, 'SELECT * FROM cron_jobs WHERE enabled = 1 ORDER BY created_at')
        return [dict(row) for row in rows]


async def add_cron_run_history(
    run_id: str, cron_job_id: str, space_id: str, status: str,
    output: str, started_at: int, finished_at: int, duration_ms: int,
) -> None:
    """记录一次定时任务执行历史。"""
    async with get_db() as conn:
        await conn.execute(
            '''INSERT INTO cron_run_history
               (id, cron_job_id, space_id, status, output, started_at, finished_at, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (run_id, cron_job_id, space_id, status, output, started_at, finished_at, duration_ms))


async def get_cron_run_history(
    space_id: str = DEFAULT_SPACE,
    limit: int = 50,
    cron_job_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """获取某空间的定时任务执行历史（最近 N 条）。"""
    async with get_db() as conn:
        query = 'SELECT * FROM cron_run_history WHERE space_id = ?'
        params: List[Any] = [space_id]
        if cron_job_id:
            query += ' AND cron_job_id = ?'
            params.append(cron_job_id)
        query += ' ORDER BY started_at DESC LIMIT ?'
        params.append(limit)
        rows = await _fetchall(conn, query, tuple(params))
        return [dict(row) for row in rows]


# ===========================================================================
# RAG 检索（向量库）数据访问层
# ===========================================================================
def _rag_source_to_dict(row) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    return {
        "id": row["id"],
        "spaceId": row["space_id"],
        "name": row["name"],
        "targetPaths": json.loads(row["target_paths"]) if row["target_paths"] else [],
        "recursive": bool(row["recursive"]),
        "fileTypes": json.loads(row["file_types"]) if row["file_types"] else [],
        "status": row["status"],
        "docCount": row["doc_count"],
        "chunkCount": row["chunk_count"],
        "embeddingModel": row["embedding_model"],
        "embedMode": row["embed_mode"],
        "error": row["error"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


async def create_rag_source(source_id: str, space_id: str, name: str, target_paths: Any,
                            recursive: bool, file_types: Any, embedding_model: str = "",
                            status: str = "pending") -> bool:
    """创建一条索引源记录（按空间打标）。target_paths / file_types 为列表。"""
    try:
        now = int(time.time() * 1000)
        async with get_db() as conn:
            await conn.execute('''
                INSERT INTO rag_sources
                (id, space_id, name, target_paths, recursive, file_types, status,
                 doc_count, chunk_count, embedding_model, embed_mode, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, 'keyword', NULL, ?, ?)
            ''', (
                source_id, space_id, name,
                json.dumps(target_paths, ensure_ascii=False),
                1 if recursive else 0,
                json.dumps(file_types, ensure_ascii=False),
                status, embedding_model, now, now,
            ))
        return True
    except Exception as e:
        print(f"Create rag source error: {e}")
        return False


async def update_rag_source(source_id: str, space_id: str, **fields: Any) -> bool:
    """白名单字段更新 rag_sources（按空间校验）。updated_at 自动刷新。"""
    allowed = {
        "name", "target_paths", "recursive", "file_types", "status",
        "doc_count", "chunk_count", "embedding_model", "embed_mode",
        "error", "updated_at",
    }
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if "updated_at" not in updates:
        updates["updated_at"] = int(time.time() * 1000)
    if not updates:
        return False
    set_clauses: List[str] = []
    values: List[Any] = []
    for key, value in updates.items():
        if key == "target_paths" and isinstance(value, (list, tuple)):
            value = json.dumps(list(value), ensure_ascii=False)
        elif key == "file_types" and isinstance(value, (list, tuple)):
            value = json.dumps(list(value), ensure_ascii=False)
        elif key == "recursive":
            value = 1 if value else 0
        set_clauses.append(f"{key} = ?")
        values.append(value)
    values.append(source_id)
    values.append(space_id)
    try:
        async with get_db() as conn:
            cur = await conn.execute(
                f"UPDATE rag_sources SET {', '.join(set_clauses)} WHERE id = ? AND space_id = ?", values)
        return cur.rowcount > 0
    except Exception as e:
        print(f"Update rag source error: {e}")
        return False


async def get_rag_source(source_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT * FROM rag_sources WHERE id = ? AND space_id = ?', (source_id, space_id))
        return _rag_source_to_dict(row) if row else None


async def get_rag_sources(space_id: str = DEFAULT_SPACE) -> List[Dict[str, Any]]:
    async with get_db() as conn:
        rows = await _fetchall(conn, 'SELECT * FROM rag_sources WHERE space_id = ? ORDER BY created_at DESC', (space_id,))
        return [_rag_source_to_dict(r) for r in rows]


async def delete_rag_source(source_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    """删除索引源 + 其下全部文档与切片（级联）。"""
    try:
        async with get_db() as conn:
            await conn.execute('DELETE FROM rag_chunks WHERE source_id = ? AND space_id = ?', (source_id, space_id))
            await conn.execute('DELETE FROM rag_documents WHERE source_id = ? AND space_id = ?', (source_id, space_id))
            cur = await conn.execute('DELETE FROM rag_sources WHERE id = ? AND space_id = ?', (source_id, space_id))
            return cur.rowcount > 0
    except Exception as e:
        print(f"Delete rag source error: {e}")
        return False


def _rag_document_to_dict(row) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    return {
        "id": row["id"],
        "spaceId": row["space_id"],
        "sourceId": row["source_id"],
        "filePath": row["file_path"],
        "fileName": row["file_name"],
        "fileType": row["file_type"],
        "fileSize": row["file_size"],
        "pageCount": row["page_count"],
        "charCount": row["char_count"],
        "chunkCount": row["chunk_count"],
        "createdAt": row["created_at"],
    }


async def create_rag_document(doc_id: str, space_id: str, source_id: str, file_path: str,
                              file_name: str, file_type: str, file_size: int = 0,
                              page_count: int = 0, char_count: int = 0, chunk_count: int = 0) -> bool:
    try:
        now = int(time.time() * 1000)
        async with get_db() as conn:
            await conn.execute('''
                INSERT INTO rag_documents
                (id, space_id, source_id, file_path, file_name, file_type, file_size,
                 page_count, char_count, chunk_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (doc_id, space_id, source_id, file_path, file_name, file_type,
                  file_size, page_count, char_count, chunk_count, now))
        return True
    except Exception as e:
        print(f"Create rag document error: {e}")
        return False


async def get_rag_documents(space_id: str = DEFAULT_SPACE, source_id: Optional[str] = None) -> List[Dict[str, Any]]:
    async with get_db() as conn:
        if source_id:
            rows = await _fetchall(conn,
                'SELECT * FROM rag_documents WHERE space_id = ? AND source_id = ? ORDER BY file_name',
                (space_id, source_id))
        else:
            rows = await _fetchall(conn,
                'SELECT * FROM rag_documents WHERE space_id = ? ORDER BY file_name', (space_id,))
        return [_rag_document_to_dict(r) for r in rows]


async def get_rag_document(doc_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT * FROM rag_documents WHERE id = ? AND space_id = ?', (doc_id, space_id))
        return _rag_document_to_dict(row) if row else None


async def update_rag_document(doc_id: str, space_id: str, chunk_count: Optional[int] = None) -> bool:
    """更新文档的切片计数（按空间校验）。"""
    try:
        async with get_db() as conn:
            cur = await conn.execute(
                'UPDATE rag_documents SET chunk_count = ? WHERE id = ? AND space_id = ?',
                (chunk_count, doc_id, space_id))
        return cur.rowcount > 0
    except Exception as e:
        print(f"Update rag document error: {e}")
        return False


async def insert_rag_chunks(chunks: List[Dict[str, Any]], space_id: str = DEFAULT_SPACE) -> int:
    """批量写入切片。chunks 元素字段见 rag_chunks 表（embedding 为 list 或 None）。"""
    if not chunks:
        return 0
    now = int(time.time() * 1000)
    try:
        async with get_db() as conn:
            for ch in chunks:
                content = _clean_text_for_db(ch.get("content", ""))
                await conn.execute('''
                    INSERT INTO rag_chunks
                    (id, space_id, source_id, doc_id, chunk_index, content, page_start, page_end,
                     char_start, char_end, embedding, token_count, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    ch["id"], space_id, ch["source_id"], ch["doc_id"], ch.get("chunk_index", 0),
                    content, ch.get("page_start"), ch.get("page_end"),
                    ch.get("char_start"), ch.get("char_end"),
                    json.dumps(ch["embedding"], ensure_ascii=False) if ch.get("embedding") else None,
                    ch.get("token_count", 0), now,
                ))
        return len(chunks)
    except Exception as e:
        print(f"Insert rag chunks error: {e}")
        return 0


async def get_rag_chunks_for_retrieval(space_id: str = DEFAULT_SPACE,
                                       source_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """取某空间（可限定来源）的全部切片 + 文档元数据，供检索排序。

    返回 list[dict]: id, sourceId, docId, content, embedding(list|None),
    pageStart, pageEnd, fileName, filePath, fileType。
    """
    async with get_db() as conn:
        if source_ids:
            placeholders = ",".join("?" for _ in source_ids)
            query = (
                "SELECT c.id, c.source_id, c.doc_id, c.content, c.embedding, c.page_start, "
                "c.page_end, d.file_name, d.file_path, d.file_type "
                "FROM rag_chunks c LEFT JOIN rag_documents d ON c.doc_id = d.id AND c.space_id = d.space_id "
                f"WHERE c.space_id = ? AND c.source_id IN ({placeholders})"
            )
            params: List[Any] = [space_id, *source_ids]
        else:
            query = (
                "SELECT c.id, c.source_id, c.doc_id, c.content, c.embedding, c.page_start, "
                "c.page_end, d.file_name, d.file_path, d.file_type "
                "FROM rag_chunks c LEFT JOIN rag_documents d ON c.doc_id = d.id AND c.space_id = d.space_id "
                "WHERE c.space_id = ?"
            )
            params = [space_id]
        rows = await _fetchall(conn, query, params)
        out: List[Dict[str, Any]] = []
        for r in rows:
            emb = None
            if r["embedding"]:
                try:
                    emb = json.loads(r["embedding"])
                except Exception:
                    emb = None
            out.append({
                "id": r["id"],
                "sourceId": r["source_id"],
                "docId": r["doc_id"],
                "content": r["content"],
                "embedding": emb,
                "pageStart": r["page_start"],
                "pageEnd": r["page_end"],
                "fileName": r["file_name"],
                "filePath": r["file_path"],
                "fileType": r["file_type"],
            })
        return out


async def get_rag_stats(space_id: str = DEFAULT_SPACE) -> Dict[str, int]:
    async with get_db() as conn:
        src = await _fetchone(conn, 'SELECT COUNT(*) AS n FROM rag_sources WHERE space_id = ?', (space_id,))
        docs = await _fetchone(conn, 'SELECT COUNT(*) AS n FROM rag_documents WHERE space_id = ?', (space_id,))
        chunks = await _fetchone(conn, 'SELECT COUNT(*) AS n FROM rag_chunks WHERE space_id = ?', (space_id,))
        vecs = await _fetchone(conn,
            "SELECT COUNT(*) AS n FROM rag_chunks WHERE space_id = ? AND embedding IS NOT NULL", (space_id,))
        return {
            "sourceCount": src["n"] if src else 0,
            "docCount": docs["n"] if docs else 0,
            "chunkCount": chunks["n"] if chunks else 0,
            "vectorCount": vecs["n"] if vecs else 0,
        }


async def _main() -> None:
    await init_db()
    old_json = DATA_DIR / 'papers' / 'metadata.json'
    if old_json.exists():
        print("Found existing JSON data, migrating...")
        await migrate_from_json(old_json)


if __name__ == '__main__':
    asyncio.run(_main())
