"""Reproduce + verify the multi-worker init_db "database is locked" race.

Spawns N processes that each call scripts.database.init_db() concurrently
against a FRESH temp DATA_DIR, mirroring uvicorn --workers N startup.

Usage: .venv/Scripts/python.exe scripts/qa_verify_init_race.py
"""
import os
import sys
import tempfile
import multiprocessing as mp

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
# 固定共享目录：Windows spawn 子进程会重新执行本模块顶层代码，若用 mkdtemp 每个
# worker 会拿到独立 DB，无法复现锁竞争。固定路径确保所有进程复用同一 DB。
SHARED_DIR = os.path.join(tempfile.gettempdir(), "airos_init_race_shared")


def worker():
    import asyncio
    # 在导入 database 之前设置共享 DATA_DIR（database 模块导入时即读取该环境变量）
    os.environ["DATA_DIR"] = SHARED_DIR
    from scripts import database
    try:
        # 多次循环以放大并发锁竞争（贴近「启动期多 worker + 请求已涌入」的负载）
        for _ in range(3):
            asyncio.run(database.init_db())
        print(f"[worker {os.getpid()}] OK")
    except Exception as e:  # noqa: BLE001
        print(f"[worker {os.getpid()}] FAIL: {type(e).__name__}: {e}")
        raise


if __name__ == "__main__":
    # 每次运行都从干净 DB 开始，顺便覆盖「首次 fresh DB」与 space_id 补列竞争
    if os.path.isdir(SHARED_DIR):
        import shutil
        shutil.rmtree(SHARED_DIR)
    N = 8
    print(f"Spawning {N} concurrent init_db() workers against {SHARED_DIR}")
    procs = [mp.Process(target=worker, daemon=True) for _ in range(N)]
    for p in procs:
        p.start()
    results = []
    for p in procs:
        p.join(timeout=60)
        results.append(p.exitcode)
    failed = [c for c in results if c is not None and c != 0]
    if not failed:
        print("RESULT: ALL_PASS — no 'database is locked' across concurrent workers")
    else:
        print(f"RESULT: FAIL — {len(failed)} worker(s) exited non-zero: {results}")
    sys.exit(1 if failed else 0)
