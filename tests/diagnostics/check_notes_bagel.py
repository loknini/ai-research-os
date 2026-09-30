"""检查当前真实数据库中是否存在与 BAGEL 相关的笔记。

警告：本诊断会读取当前 ``DATA_DIR``，不是隔离测试，也不会修改数据。
"""
from __future__ import annotations

import asyncio

from scripts import database


async def main() -> None:
    await database.init_db()
    notes = await database.get_all_notes()
    print(f"Total notes: {len(notes)}")
    matches = []
    for note in notes:
        title = (note.get("title") or "").lower()
        content = (note.get("content") or "").lower()
        if "bagel" in title or "bagel" in content:
            matches.append(note)
    if not matches:
        print("未找到任何包含 BAGEL 的笔记。")
        return
    print(f"找到 {len(matches)} 条含 BAGEL 的笔记：")
    for match in matches:
        print(
            f"- id={match['id']} title={match.get('title')!r} "
            f"updatedAt={match.get('updatedAt')} aiGenerated={match.get('aiGenerated')}"
        )
        content = match.get("content") or ""
        print(f"  content preview: {content[:200]!r}")


if __name__ == "__main__":
    asyncio.run(main())
