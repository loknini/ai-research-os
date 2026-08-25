"""一次性清洗：还原 Chat Hub 因 SSE 解析 bug 而错存进库的原始帧。

背景
----
修复前，前端把每个 SSE 帧(带 `data: ` 前缀的原始行)直接累加进 `fullContent`，
最终作为 assistant 消息的 content 原样写入 chat_messages。该 content 形如：
    data: {"type":"text","content":"你好"}data: {"type":"text","content":"！"}...data: [DONE]

本脚本把这些帧反向解析，提取每个 `text` 帧的 content 拼回成干净文本，UPDATE 回库。
- 只处理 role='assistant' 且 content 含污染特征 `data: {"type` 的行（精确过滤，绝不误伤正常消息）。
- 可重入：清洗后 content 不再含该特征，再次运行会跳过。
- 默认 dry-run（只统计+打印样例）；加 --apply 才真正写库，写前自动备份 db 三件套。
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import aiosqlite

# --- 解析真实库路径（与 config.py 保持一致）---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR") or (PROJECT_ROOT / "data"))
DB_PATH = Path(os.environ.get("DB_PATH") or (DATA_DIR / "ai_research_os.db"))

CORRUPT_SIGNATURE = 'data: {"type'


def extract_object(s: str, start: int):
    """从 s[start]=='{' 起，用括号计数(尊重 JSON 字符串/转义)提取一个完整对象。
    返回 (obj_str, end_exclusive)；失败返回 (None, start+1)。"""
    depth = 0
    in_str = False
    esc = False
    i = start
    n = len(s)
    while i < n:
        c = s[i]
        if esc:
            esc = False
        elif c == '\\':
            esc = True
        elif c == '"':
            in_str = not in_str
        elif not in_str:
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    return s[start:i + 1], i + 1
        i += 1
    return None, start + 1


def recover_text(raw: str) -> str:
    """把拼接的原始 SSE 帧还原为干净文本。"""
    parts = []
    i = 0
    while True:
        idx = raw.find(CORRUPT_SIGNATURE, i)
        if idx == -1:
            break
        brace = raw.find('{', idx)
        if brace == -1:
            break
        obj_str, end = extract_object(raw, brace)
        if obj_str is None:
            i = brace + 1
            continue
        try:
            obj = json.loads(obj_str)
        except Exception:
            i = end
            continue
        t = obj.get('type')
        if t == 'text' and obj.get('content'):
            parts.append(obj['content'])
        elif t == 'error':
            parts.append('\n[错误: ' + str(obj.get('error', '')) + ']')
        # tool_start / tool_result / context 等帧忽略
        i = end
    return ''.join(parts)


def is_corrupted(content: str) -> bool:
    return CORRUPT_SIGNATURE in content


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='真正写库（默认 dry-run）')
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f'[ERR] 数据库不存在: {DB_PATH}')
        sys.exit(1)

    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        rows = await (await conn.execute(
            "SELECT id, conversation_id, role, content FROM chat_messages "
            "WHERE role='assistant'"
        )).fetchall()

    corrupted = [(r['id'], r['conversation_id'], r['content']) for r in rows if is_corrupted(r['content'] or '')]

    print(f'扫描 chat_messages(assistant): 共 {len(rows)} 条，其中被污染 {len(corrupted)} 条')
    print(f'数据库: {DB_PATH}')

    if not corrupted:
        print('RESULT: 无需清洗，数据库干净。')
        return

    # 打印前 2 条样例（前 120 字）
    for cid, conv, content in corrupted[:2]:
        cleaned = recover_text(content)
        print('\n--- 样例 ---')
        print(f'  message_id={cid}  conversation_id={conv}')
        print(f'  脏内容(前120): {content[:120]!r}')
        print(f'  清洗后(前120): {cleaned[:120]!r}')

    if not args.apply:
        print('\n[DRY-RUN] 未写库。加 --apply 执行真正清洗（会自动备份）。')
        return

    # --- 写库前备份 db 三件套 ---
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_dir = DATA_DIR / f'backup_chatfix_{ts}'
    backup_dir.mkdir(parents=True, exist_ok=True)
    for suffix in ('', '-wal', '-shm'):
        p = DB_PATH.with_suffix(DB_PATH.suffix + suffix) if suffix else DB_PATH
        if p.exists():
            shutil.copy2(p, backup_dir / p.name)
    print(f'\n[OK] 已备份至: {backup_dir}')

    fixed = 0
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        for mid, conv, content in corrupted:
            cleaned = recover_text(content)
            if not cleaned:
                continue
            await conn.execute(
                'UPDATE chat_messages SET content=? WHERE id=?',
                (cleaned, mid),
            )
            fixed += 1
        await conn.commit()

    print(f'[OK] 已清洗 {fixed} 条 assistant 消息。刷新页面即可看到还原后的内容。')
    print('RESULT: ALL_DONE')


if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
