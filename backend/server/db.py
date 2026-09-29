"""数据库引导模块。

在进程内导入正规的 ``scripts.database`` 兼容门面并向路由重新导出。该门面把工作
委托给 ``scripts.db`` 的连接内核、版本化迁移和领域仓储。

导入本模块时，``config.py`` 已把 ``DATA_DIR`` 与 ``DB_PATH`` 写入环境变量，
因此 ``database`` 会解析到正确的 SQLite 文件。
"""
from __future__ import annotations

from scripts import database  # noqa: F401  (scripts.database 正规包导入)

from .core import config


async def init_db() -> None:
    """初始化 SQLite schema；操作幂等，可在启动阶段安全调用。"""
    await database.init_db()


__all__ = ["database", "init_db", "config"]
