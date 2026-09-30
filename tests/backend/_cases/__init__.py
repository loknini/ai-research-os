"""从旧 QA 脚本迁入的隔离回归实现。

这些模块由 pytest 领域测试通过独立子进程执行，不作为公开测试入口。
"""
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
