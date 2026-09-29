"""后端脚本正规包及 QA 运行环境入口。

数据库、论文抓取和服务适配器都通过 ``scripts`` 的正规包路径导入。使用
``python -m scripts.qa_verify_*`` 运行 QA 时，本模块会在导入应用前把持久日志重定向到
系统临时目录，并在进程退出时自动清理，避免测试日志污染项目的正式 ``logs/``。
"""
from __future__ import annotations

import atexit
import os
import sys
import tempfile
from pathlib import Path


_qa_log_temp: tempfile.TemporaryDirectory[str] | None = None


def _configure_qa_log_isolation() -> None:
    global _qa_log_temp
    entry_name = Path(sys.argv[0] or "").stem
    original_args = list(getattr(sys, "orig_argv", ()) or ())
    if "-m" in original_args:
        module_index = original_args.index("-m") + 1
        if module_index < len(original_args):
            entry_name = original_args[module_index].rsplit(".", 1)[-1]
    if not entry_name.startswith("qa_verify_") or os.environ.get("LOG_DIR"):
        return
    _qa_log_temp = tempfile.TemporaryDirectory(prefix=f"airos-{entry_name}-logs-")
    os.environ["LOG_DIR"] = _qa_log_temp.name
    atexit.register(_qa_log_temp.cleanup)


_configure_qa_log_isolation()
