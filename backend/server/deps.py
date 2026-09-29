"""用于 space-key 软隔离的 FastAPI 依赖。

请求的 ``space_id`` 来自 ``X-Space-Key`` 请求头：

* ``normalize_space_key`` 去除首尾空白并转为小写；不做哈希，因为键本身就是匿名身份维度；
* 每条数据路由都在处理器层注入 ``get_space_id``，把解析结果直接传给数据库层。

``settings``、``healthz``、``backup`` 等系统路由有意不使用此依赖，因为它们分别属于
全局配置、存活检查和全局备份端点，不参与空间隔离。
"""
from __future__ import annotations

from fastapi import Header, HTTPException

# 暴露给本模块与调用方复用，保持与 scripts/database.py 默认空间一致。
DEFAULT_SPACE = "__default__"

# space key 归一后的最小长度（允许中文 / 字母 / 数字 / 常见符号）。
MIN_KEY_LEN = 4


def normalize_space_key(raw: str) -> str:
    """去除首尾空白并转为小写，不做哈希。

    参数 ``raw`` 是原始 ``X-Space-Key`` 请求头；输入缺失时返回空字符串，否则返回
    规范化后的空间键。
    """
    return (raw or "").strip().lower()


async def get_space_id(x_space_key: str = Header(default=None, alias="X-Space-Key")) -> str:
    """从 ``X-Space-Key`` 请求头解析 ``space_id``。

    请求头缺失或为空时返回 HTTP 400；规范化后长度小于 4 时也返回 HTTP 400。
    成功时返回规范化后的 ``space_id``；``__default__`` 精确对应历史共享空间。
    """
    if not x_space_key or not x_space_key.strip():
        raise HTTPException(status_code=400, detail="Missing X-Space-Key header")
    key = normalize_space_key(x_space_key)
    if len(key) < MIN_KEY_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"X-Space-Key too short (min {MIN_KEY_LEN} chars after normalization)",
        )
    return key


__all__ = ["DEFAULT_SPACE", "MIN_KEY_LEN", "normalize_space_key", "get_space_id"]
