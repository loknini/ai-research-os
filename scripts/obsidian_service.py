#!/usr/bin/env python3
"""
Obsidian Vault 服务
提供 Vault 扫描、文件导入、Markdown 解析等功能

space-key 软隔离：vault 元数据按 ``SPACE_ID`` 环境变量（由后端 router 注入）
隔离；vault 文件本体仍在用户外部路径，本服务只管理元数据命名空间。
"""
from __future__ import annotations

import os
import re
import json
import hashlib
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict

# 数据库路径（与后端 config.DB_PATH 一致；尊重 DATA_DIR 覆盖）。
_DATA_DIR = os.environ.get("DATA_DIR")
DB_PATH = (
    os.path.join(_DATA_DIR, "ai_research_os.db")
    if _DATA_DIR
    else os.path.join(os.path.dirname(__file__), "..", "data", "ai_research_os.db")
)

# 当前空间（由后端 router 经环境变量注入；缺省走默认空间，保持向后兼容）。
DEFAULT_SPACE = "__default__"


@dataclass
class ParsedNote:
    """解析后的笔记数据结构"""
    path: str
    title: str
    content: str
    frontmatter: Dict[str, Any]
    tags: List[str]
    links: List[Dict[str, str]]
    attachments: List[str]
    modified_time: int


class ObsidianParser:
    """Obsidian Markdown 解析器"""

    def __init__(self, vault_path: str):
        self.vault_path = Path(vault_path)

    def parse_file(self, relative_path: str) -> Optional[ParsedNote]:
        file_path = self.vault_path / relative_path
        if not file_path.exists():
            return None
        try:
            content = file_path.read_text(encoding='utf-8')
            modified_time = int(file_path.stat().st_mtime)
            frontmatter, body = self._split_frontmatter(content)
            title = self._extract_title(body) or file_path.stem
            tags = self._extract_tags(body, frontmatter.get('tags', []))
            links = self._extract_links(body)
            attachments = self._extract_attachments(body)
            return ParsedNote(
                path=relative_path,
                title=title,
                content=body,
                frontmatter=frontmatter,
                tags=tags,
                links=links,
                attachments=attachments,
                modified_time=modified_time
            )
        except Exception as e:
            print(f"Error parsing {relative_path}: {e}")
            return None

    def _split_frontmatter(self, content: str) -> Tuple[Dict[str, Any], str]:
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                try:
                    import yaml
                    frontmatter = yaml.safe_load(parts[1]) or {}
                    return frontmatter, parts[2].strip()
                except Exception:
                    pass
        return {}, content

    def _extract_title(self, content: str) -> Optional[str]:
        match = re.search(r'^# (.+)$', content, re.MULTILINE)
        if match:
            return match.group(1).strip()
        return None

    def _extract_tags(self, content: str, frontmatter_tags: List[str]) -> List[str]:
        inline_tags = re.findall(r'#([\w\u4e00-\u9fff]+)', content)
        all_tags = list(set(frontmatter_tags + inline_tags))
        return all_tags

    def _extract_links(self, content: str) -> List[Dict[str, str]]:
        pattern = r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]'
        links = []
        for match in re.finditer(pattern, content):
            target = match.group(1).strip()
            alias = match.group(2).strip() if match.group(2) else target
            links.append({'target': target, 'alias': alias})
        return links

    def _extract_attachments(self, content: str) -> List[str]:
        attachments = []
        std_images = re.findall(r'!\[([^\]]*)\]\(([^)]+)\)', content)
        attachments.extend([img[1] for img in std_images])
        obs_embeds = re.findall(r'!\[\[([^\]]+)\]\]', content)
        attachments.extend(obs_embeds)
        return attachments


class VaultScanner:
    """Vault 扫描器"""

    def __init__(self, vault_path: str):
        self.vault_path = Path(vault_path)
        self.parser = ObsidianParser(vault_path)

    def scan(self) -> Dict[str, Any]:
        markdown_files = []
        attachments = []
        errors = []

        ignore_dirs = {'.obsidian', '.git', 'node_modules'}

        for root, dirs, files in os.walk(self.vault_path):
            dirs[:] = [d for d in dirs if d not in ignore_dirs]
            for file in files:
                file_path = Path(root) / file
                relative_path = file_path.relative_to(self.vault_path)
                try:
                    if file.endswith('.md'):
                        note = self.parser.parse_file(str(relative_path))
                        if note:
                            markdown_files.append(note)
                    else:
                        attachments.append({
                            'path': str(relative_path),
                            'size': file_path.stat().st_size
                        })
                except Exception as e:
                    errors.append({'path': str(relative_path), 'error': str(e)})

        return {
            'markdown_files': markdown_files,
            'attachments': attachments,
            'errors': errors,
            'total_files': len(markdown_files) + len(attachments)
        }


class ObsidianService:
    """Obsidian 服务主类"""

    def __init__(self, space_id: Optional[str] = None):
        self.db_path = DB_PATH
        self.space_id = (space_id or os.environ.get("SPACE_ID") or DEFAULT_SPACE)

    def _get_db(self):
        """获取数据库连接（设置 busy_timeout 以抗多 worker 并发锁）。"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        # WAL 为持久属性（后端 init_db 已设置），此处再声明一次以保稳妥。
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass
        return conn

    def add_vault(self, name: str, vault_path: str) -> Dict[str, Any]:
        path = Path(vault_path)
        if not path.exists():
            return {'success': False, 'message': '路径不存在'}
        if not path.is_dir():
            return {'success': False, 'message': '路径不是目录'}

        with self._get_db() as conn:
            existing = conn.execute(
                'SELECT id FROM obsidian_vaults WHERE vault_path = ? AND space_id = ?',
                (vault_path, self.space_id)
            ).fetchone()
            if existing:
                return {'success': False, 'message': '该 Vault 已存在'}

            cursor = conn.execute(
                '''INSERT INTO obsidian_vaults (name, vault_path, space_id)
                   VALUES (?, ?, ?)''',
                (name, vault_path, self.space_id)
            )
            vault_id = cursor.lastrowid
            conn.commit()
            return {
                'success': True,
                'vault': {'id': vault_id, 'name': name, 'path': vault_path}
            }

    def list_vaults(self) -> List[Dict[str, Any]]:
        with self._get_db() as conn:
            rows = conn.execute(
                '''SELECT v.*, COUNT(f.id) as file_count
                   FROM obsidian_vaults v
                   LEFT JOIN obsidian_files f ON v.id = f.vault_id AND f.space_id = v.space_id
                   WHERE v.is_active = 1 AND v.space_id = ?
                   GROUP BY v.id''',
                (self.space_id,)
            ).fetchall()
            return [{
                'id': row['id'],
                'name': row['name'],
                'path': row['vault_path'],
                'sync_mode': row['sync_mode'],
                'last_sync_at': row['last_sync_at'],
                'file_count': row['file_count'],
                'is_active': row['is_active']
            } for row in rows]

    def scan_vault(self, vault_id: int) -> Dict[str, Any]:
        with self._get_db() as conn:
            vault = conn.execute(
                'SELECT * FROM obsidian_vaults WHERE id = ? AND space_id = ?',
                (vault_id, self.space_id)
            ).fetchone()
            if not vault:
                return {'success': False, 'message': 'Vault 不存在'}

            scanner = VaultScanner(vault['vault_path'])
            result = scanner.scan()

            added = 0
            updated = 0
            for note in result['markdown_files']:
                content_hash = hashlib.md5(note.content.encode('utf-8')).hexdigest()
                existing = conn.execute(
                    '''SELECT id, file_hash FROM obsidian_files
                       WHERE vault_id = ? AND relative_path = ? AND space_id = ?''',
                    (vault_id, note.path, self.space_id)
                ).fetchone()

                if existing:
                    if existing['file_hash'] != content_hash:
                        conn.execute(
                            '''UPDATE obsidian_files
                               SET file_hash = ?,
                                   modified_time = ?,
                                   content_preview = ?,
                                   frontmatter = ?,
                                   tags = ?,
                                   links = ?,
                                   sync_status = 'synced',
                                   last_sync_at = strftime('%s', 'now')
                               WHERE id = ? AND space_id = ?''',
                            (
                                content_hash,
                                note.modified_time,
                                note.content[:500],
                                json.dumps(note.frontmatter),
                                json.dumps(note.tags),
                                json.dumps(note.links),
                                existing['id'],
                                self.space_id
                            )
                        )
                        updated += 1
                else:
                    conn.execute(
                        '''INSERT INTO obsidian_files
                           (vault_id, relative_path, file_hash, modified_time,
                            content_preview, frontmatter, tags, links,
                            sync_status, last_sync_at, space_id)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'synced', strftime('%s', 'now'), ?)''',
                        (
                            vault_id,
                            note.path,
                            content_hash,
                            note.modified_time,
                            note.content[:500],
                            json.dumps(note.frontmatter),
                            json.dumps(note.tags),
                            json.dumps(note.links),
                            self.space_id
                        )
                    )
                    added += 1

            conn.execute(
                '''UPDATE obsidian_vaults
                   SET last_sync_at = strftime('%s', 'now')
                   WHERE id = ? AND space_id = ?''',
                (vault_id, self.space_id)
            )
            conn.commit()

            return {
                'success': True,
                'scanned': result['total_files'],
                'added': added,
                'updated': updated,
                'errors': len(result['errors'])
            }

    def get_vault_files(self, vault_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        with self._get_db() as conn:
            rows = conn.execute(
                '''SELECT * FROM obsidian_files
                   WHERE vault_id = ? AND space_id = ?
                   ORDER BY modified_time DESC
                   LIMIT ?''',
                (vault_id, self.space_id, limit)
            ).fetchall()
            return [{
                'id': row['id'],
                'path': row['relative_path'],
                'title': Path(row['relative_path']).stem,
                'tags': json.loads(row['tags']) if row['tags'] else [],
                'modified_at': row['modified_time'],
                'sync_status': row['sync_status']
            } for row in rows]

    def get_file_content(self, file_id: int) -> Optional[Dict[str, Any]]:
        with self._get_db() as conn:
            row = conn.execute(
                '''SELECT f.*, v.vault_path
                   FROM obsidian_files f
                   JOIN obsidian_vaults v ON f.vault_id = v.id
                   WHERE f.id = ? AND f.space_id = ?''',
                (file_id, self.space_id)
            ).fetchone()
            if not row:
                return None
            file_path = Path(row['vault_path']) / row['relative_path']
            try:
                content = file_path.read_text(encoding='utf-8')
            except Exception:
                content = None
            return {
                'id': row['id'],
                'path': row['relative_path'],
                'title': Path(row['relative_path']).stem,
                'content': content,
                'frontmatter': json.loads(row['frontmatter']) if row['frontmatter'] else {},
                'tags': json.loads(row['tags']) if row['tags'] else [],
                'links': json.loads(row['links']) if row['links'] else [],
                'modified_at': row['modified_time']
            }


# 命令行接口
if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python obsidian_service.py <command> [args]")
        sys.exit(1)

    # 子进程由后端 router 注入 SPACE_ID 环境变量；缺省默认空间。
    service = ObsidianService(space_id=os.environ.get("SPACE_ID"))

    command = sys.argv[1]

    if command == 'add_vault':
        name = sys.argv[2]
        path = sys.argv[3]
        result = service.add_vault(name, path)
        print(json.dumps(result))

    elif command == 'list_vaults':
        vaults = service.list_vaults()
        print(json.dumps({'success': True, 'vaults': vaults}))

    elif command == 'scan':
        vault_id = int(sys.argv[2])
        result = service.scan_vault(vault_id)
        print(json.dumps(result))

    elif command == 'list_files':
        vault_id = int(sys.argv[2])
        files = service.get_vault_files(vault_id)
        print(json.dumps({'success': True, 'files': files}))

    elif command == 'get_content':
        file_id = int(sys.argv[2])
        content = service.get_file_content(file_id)
        print(json.dumps({'success': True, 'file': content}))

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
