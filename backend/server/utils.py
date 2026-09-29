"""不依赖外部包的小型后端共享辅助函数。"""

from __future__ import annotations


def mask_key(key: str) -> str:
    """返回可安全展示的 API Key 脱敏形式。

    长 Key 保留首尾各 4 个字符，中间用 6 个星号遮盖；不超过 8 个字符的 Key 全部
    遮盖。这是唯一标准实现，用于消除过去 ``llm.py`` 与 ``settings.py`` 的行为差异。
    """
    key = key or ""
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}{'*' * 6}{key[-4:]}"
