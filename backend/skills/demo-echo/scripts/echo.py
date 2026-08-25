#!/usr/bin/env python3
"""示例技能：由 SkillBridge 通过 subprocess 调用。

从 stdin 读取 JSON 参数，回显文本并读取环境变量 X_SPACE_KEY（空间隔离），
将结果以 JSON 写入 stdout。用于端到端验证 SkillBridge 管线。
"""
import json
import os
import sys


def main() -> None:
    raw = sys.stdin.read()
    try:
        params = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        params = {}
    space = os.environ.get("X_SPACE_KEY", "__default__")
    result = {
        "success": True,
        "echo": params.get("text", ""),
        "space": space,
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
