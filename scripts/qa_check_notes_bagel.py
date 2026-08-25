"""检查数据库中是否存在与 BAGEL 相关的笔记，验证 AI 是否真的创建了笔记。"""
import asyncio
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from scripts import database


async def main():
    await database.init_db()
    notes = await database.get_all_notes()
    print(f"Total notes: {len(notes)}")
    matches = []
    for n in notes:
        title = (n.get("title") or "").lower()
        content = (n.get("content") or "").lower()
        if "bagel" in title or "bagel" in content:
            matches.append(n)
    if not matches:
        print("未找到任何包含 BAGEL 的笔记。")
        return
    print(f"找到 {len(matches)} 条含 BAGEL 的笔记：")
    for m in matches:
        print(f"- id={m['id']} title={m.get('title')!r} updatedAt={m.get('updatedAt')} aiGenerated={m.get('aiGenerated')}")
        # 打印前 200 字符确认内容
        content = m.get("content") or ""
        print(f"  content preview: {content[:200]!r}")


if __name__ == "__main__":
    asyncio.run(main())
