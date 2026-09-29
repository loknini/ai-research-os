"""备份导出、校验、原子导入与故障恢复服务。

导出会将 ``DATA_DIR`` 打包到内存 ZIP，排除缓存、运行协调文件和 SQLite
临时文件，并在包根写入 ``manifest.json``。导入先完整暂存并校验压缩包，再快照
现有数据，最后通过原子替换或 SQLite Online Backup 应用；任何失败都会恢复本次
导入触碰过的目标。

本模块承载应用服务逻辑，不声明 HTTP 路由。管理权限和上传字段约束由
``routers/backup.py`` 负责。
"""
from __future__ import annotations

import io
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from fastapi import HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from ..core import config

logger = logging.getLogger(__name__)

APP_NAME = "ai-research-os"
MANIFEST_VERSION = "0.1"

# 导入和导出时都排除的目录（临时文件、缓存和内部状态）。
EXCLUDE_DIRS = {".git", ".openclaw", ".swanlab", ".cache", "__pycache__"}

# OpenClaw 遗留的 agent 人设文件（非 app 数据），无论出现在 DATA_DIR 哪一层都剔除。
EXCLUDE_FILES = {
    "AGENTS.md",
    "BOOTSTRAP.md",
    "HEARTBEAT.md",
    "IDENTITY.md",
    "SOUL.md",
    "TOOLS.md",
    "USER.md",
    # 运行时协调状态会在启动时重新生成；在 Windows 上还可能被实例心跳线程并发替换。
    ".backend_supervisors.json",
    ".backend_supervisors.json.tmp",
    ".backend_supervisors.lock",
    ".airos-backup-operation.lock",
    ".airos-backup-import.json",
    ".airos-backup-import.json.tmp",
    ".airos-schema-migration.lock",
}

# 上传备份的硬性大小上限，用于防止滥用（500 MB）。
MAX_IMPORT_BYTES = 500 * 1024 * 1024
MAX_EXTRACT_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 100_000
BACKUP_LOCK_STALE_SECONDS = 24 * 60 * 60
IMPORT_JOURNAL_NAME = ".airos-backup-import.json"


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------
def _utcnow_iso() -> str:
    """返回 ISO-8601 格式的当前 UTC 时间。"""
    return datetime.now(timezone.utc).isoformat()


def _timestamp() -> str:
    """返回适合文件名且精度足以区分并发导入的时间戳。"""
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _top_entries(data_dir: Path) -> List[str]:
    """返回 ``DATA_DIR`` 顶层条目名的排序列表，并排除临时内容。"""
    return sorted(
        p.name
        for p in data_dir.iterdir()
        if not _is_excluded(Path(p.name), config.DB_PATH.name)
    )


def _is_excluded(rel: Path, db_name: str) -> bool:
    """判断 DATA_DIR 相对路径是否属于运行时或缓存状态。"""
    if any(part in EXCLUDE_DIRS for part in rel.parts):
        return True
    if rel.name in EXCLUDE_FILES:
        return True
    if rel.name in {f"{db_name}-wal", f"{db_name}-shm", f"{db_name}-journal"}:
        return True
    # 防御性处理：未来导出实现可能从内存缓冲区改为 DATA_DIR 下的文件，
    # 因此绝不能把本次导出文件递归打包进自身。
    return rel.name.startswith("airos-backup-") and rel.suffix.lower() == ".zip"


def _sqlite_snapshot(source: Path, destination: Path) -> None:
    """创建事务一致的 SQLite 快照。

    只复制活动 WAL 数据库的主文件可能静默遗漏最近提交；SQLite Online Backup API
    会一致地读取主数据库与 WAL。
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(source), timeout=10)
    dst = sqlite3.connect(str(destination), timeout=10)
    try:
        src.backup(dst)
        result = dst.execute("PRAGMA integrity_check").fetchone()
        if not result or str(result[0]).lower() != "ok":
            raise sqlite3.DatabaseError(f"integrity_check failed: {result!r}")
    finally:
        dst.close()
        src.close()


def _safe_add_db(zf: zipfile.ZipFile, source: Path, arcname: str) -> None:
    """把一致的 SQLite 快照加入归档。"""
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
            tmp_path = Path(tmp.name)
        _sqlite_snapshot(source, tmp_path)
        zf.write(tmp_path, arcname)
    except (OSError, sqlite3.Error) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"数据库一致性快照失败，未生成不完整备份：{exc}",
        ) from exc
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _snapshot_data_dir(data_dir: Path, target: Path, db_path: Path) -> None:
    """备份当前数据，但不复制锁、WAL 文件或活动数据库的原始字节。"""
    target.mkdir(parents=True, exist_ok=False)
    db_resolved = db_path.resolve()
    db_added = False
    for item in sorted(data_dir.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(data_dir)
        if _is_excluded(rel, db_path.name):
            continue
        destination = target / rel
        if item.resolve() == db_resolved:
            _sqlite_snapshot(item, destination)
            db_added = True
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)
    if db_path.is_file() and not db_added:
        _sqlite_snapshot(db_path, target / db_path.name)


def _validate_member_names(names: List[str]) -> None:
    """拒绝试图逃逸解压根目录的 ZIP 条目，防止 Zip Slip。"""
    seen: set[str] = set()
    for name in names:
        normalized = name.replace("\\", "/")
        parts = normalized.split("/")
        if ("\x00" in normalized or normalized.startswith("/") or ".." in parts
                or "." in parts or (parts and ":" in parts[0])):
            raise HTTPException(
                status_code=400, detail="备份包包含非法路径，已拒绝导入"
            )
        identity = normalized.rstrip("/").casefold()
        if identity in seen:
            raise HTTPException(status_code=400, detail="备份包包含重复路径，已拒绝导入")
        seen.add(identity)


def _atomic_copy_file(source: Path, target: Path) -> None:
    """复制普通文件，并原子替换目标。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False,
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".importing",
        ) as tmp:
            tmp_path = Path(tmp.name)
            with source.open("rb") as src:
                shutil.copyfileobj(src, tmp)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, target)
        tmp_path = None
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _validate_sqlite_file(path: Path) -> None:
    """在修改线上数据前校验并拒绝无效的待导入数据库。"""
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=400, detail=f"备份数据库无效：{exc}") from exc
    if not result or str(result[0]).lower() != "ok":
        raise HTTPException(status_code=400, detail=f"备份数据库完整性检查失败：{result!r}")


def _import_target(data_dir: Path, db_path: Path, rel: Path) -> tuple[Path, bool]:
    """把单个暂存文件解析为安全的线上目标路径。"""
    is_db = rel.parts == (db_path.name,)
    if is_db:
        if db_path.exists() and not db_path.is_file():
            raise HTTPException(status_code=400, detail="数据库导入目标不是文件")
        return db_path, True
    target = data_dir / rel
    # DATA_DIR 中已有的符号链接不得把导入内容重定向到其他位置。
    try:
        target.resolve(strict=False).relative_to(data_dir.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"导入目标越界：{rel}") from exc
    cursor = data_dir
    for index, part in enumerate(rel.parts):
        cursor = cursor / part
        if cursor.is_symlink():
            raise HTTPException(status_code=400, detail=f"导入目标包含符号链接：{rel}")
        if cursor.exists():
            is_leaf = index == len(rel.parts) - 1
            if (is_leaf and not cursor.is_file()) or (not is_leaf and not cursor.is_dir()):
                raise HTTPException(status_code=400, detail=f"导入目标类型冲突：{rel}")
    return target, False


def _rollback_import(
    applied: list[tuple[Path, Path, bool, bool]],
    backup_path: Path,
    db_name: str,
) -> list[str]:
    """按逆序恢复失败导入触及的每个目标。"""
    failures: list[str] = []
    for target, rel, is_db, existed in reversed(applied):
        original = backup_path / (db_name if is_db else rel)
        try:
            if existed:
                if not original.is_file():
                    raise FileNotFoundError(f"回滚快照缺少 {rel}")
                if is_db:
                    _sqlite_snapshot(original, target)
                else:
                    _atomic_copy_file(original, target)
            elif target.exists():
                target.unlink()
        except (OSError, sqlite3.Error) as exc:
            failures.append(f"{rel}: {exc}")
    return failures


def _claim_backup_operation(data_dir: Path) -> Path:
    """通过独占创建文件获取跨进程导入/导出锁。"""
    data_dir.mkdir(parents=True, exist_ok=True)
    lock_path = data_dir / ".airos-backup-operation.lock"
    for attempt in range(2):
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, f"pid={os.getpid()} time={time.time()}\n".encode("ascii"))
            finally:
                os.close(fd)
            return lock_path
        except FileExistsError as exc:
            owner_alive = False
            try:
                raw = lock_path.read_text(encoding="ascii", errors="ignore")
                match = next(
                    (part for part in raw.split() if part.startswith("pid=")), ""
                )
                owner_pid = int(match.split("=", 1)[1]) if match else 0
                if owner_pid > 0:
                    try:
                        os.kill(owner_pid, 0)
                        owner_alive = True
                    except PermissionError:
                        owner_alive = True
                    except OSError:
                        owner_alive = False
            except (OSError, ValueError):
                owner_alive = False
            try:
                stale = time.time() - lock_path.stat().st_mtime > BACKUP_LOCK_STALE_SECONDS
            except OSError:
                stale = False
            if (stale or not owner_alive) and attempt == 0:
                try:
                    lock_path.unlink()
                    continue
                except OSError:
                    pass
            raise HTTPException(
                status_code=409,
                detail="已有备份导入或导出正在执行，请稍后重试",
            ) from exc
    raise HTTPException(status_code=409, detail="无法获取备份操作锁")


def _release_backup_operation(lock_path: Path | None) -> None:
    if lock_path is None:
        return
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


def _write_import_journal(
    data_dir: Path,
    backup_path: Path,
    plan: list[tuple[Path, Path, bool, bool]],
    state: str,
) -> Path:
    """持久记录进程异常退出后恢复所需的完整信息。"""
    journal_path = data_dir / IMPORT_JOURNAL_NAME
    payload = {
        "version": 1,
        "state": state,
        "backupPath": str(backup_path.resolve()),
        "targets": [
            {
                "rel": rel.as_posix(),
                "isDb": is_db,
                "existed": existed,
            }
            for _, rel, is_db, existed in plan
        ],
    }
    tmp_path = journal_path.with_suffix(".json.tmp")
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    with tmp_path.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, journal_path)
    return journal_path


def recover_interrupted_import(wait_seconds: float = 30.0) -> bool:
    """在应用打开数据库前恢复被中断的导入。

    多个 Uvicorn Worker 可能同时启动；只有一个能取得备份锁，其余 Worker 等待恢复
    日志消失，避免并发恢复。
    """
    data_dir = config.DATA_DIR
    journal_path = data_dir / IMPORT_JOURNAL_NAME
    if not journal_path.is_file():
        return False
    deadline = time.monotonic() + max(0.1, wait_seconds)
    operation_lock: Path | None = None
    while operation_lock is None:
        if not journal_path.is_file():
            return False
        try:
            operation_lock = _claim_backup_operation(data_dir)
        except HTTPException as exc:
            if exc.status_code != 409 or time.monotonic() >= deadline:
                raise RuntimeError("等待备份导入恢复锁超时") from exc
            time.sleep(0.1)

    try:
        payload = json.loads(journal_path.read_text(encoding="utf-8"))
        if payload.get("version") != 1:
            raise RuntimeError("不支持的备份导入恢复日志版本")
        if payload.get("state") == "committed":
            journal_path.unlink(missing_ok=True)
            return False
        backup_path = Path(str(payload.get("backupPath") or "")).resolve()
        expected_parent = data_dir.parent.resolve()
        if backup_path.parent != expected_parent or not backup_path.name.startswith(".backup-"):
            raise RuntimeError("备份导入恢复日志中的快照路径非法")
        targets = payload.get("targets")
        if not isinstance(targets, list) or not targets:
            raise RuntimeError("备份导入恢复日志缺少目标清单")
        restore_plan: list[tuple[Path, Path, bool, bool]] = []
        for item in targets:
            if not isinstance(item, dict):
                raise RuntimeError("备份导入恢复日志目标格式错误")
            rel_text = str(item.get("rel") or "")
            _validate_member_names([rel_text])
            rel = Path(rel_text)
            target, is_db = _import_target(data_dir, config.DB_PATH, rel)
            if is_db != bool(item.get("isDb")):
                raise RuntimeError(f"备份导入恢复目标类型不匹配：{rel}")
            restore_plan.append((target, rel, is_db, bool(item.get("existed"))))
        failures = _rollback_import(restore_plan, backup_path, config.DB_PATH.name)
        if failures:
            raise RuntimeError("备份导入自动恢复失败：" + "；".join(failures))
        journal_path.unlink(missing_ok=True)
        logger.warning("backup.interrupted_import_recovered path=%s", backup_path)
        return True
    finally:
        _release_backup_operation(operation_lock)


# ---------------------------------------------------------------------------
# 导出
# ---------------------------------------------------------------------------
async def export_backup() -> StreamingResponse:
    """流式返回含 ``manifest.json`` 的 DATA_DIR ZIP，并排除临时内容。"""
    data_dir: Path = config.DATA_DIR
    if not data_dir.exists():
        raise HTTPException(status_code=404, detail="数据目录不存在，无法导出备份")

    db_path: Path = config.DB_PATH
    filename = f"airos-backup-{_timestamp()}.zip"

    buf = io.BytesIO()
    operation_lock = _claim_backup_operation(data_dir)
    try:
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            manifest = {
                "app": APP_NAME,
                "version": MANIFEST_VERSION,
                "exported_at": _utcnow_iso(),
                "entries": _top_entries(data_dir),
                "db_relative": db_path.name,
            }
            zf.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )

            db_added = False
            for item in sorted(data_dir.rglob("*")):
                if not item.is_file():
                    continue
                rel = item.relative_to(data_dir)
                if _is_excluded(rel, db_path.name):
                    continue
                arcname = str(rel)
                if item.resolve() == db_path.resolve():
                    _safe_add_db(zf, item, arcname)
                    db_added = True
                else:
                    zf.write(item, arcname)

            # DB_PATH 可能有意设置在 DATA_DIR 之外，但可移植备份仍需按清单声明的
            # 根文件名包含该数据库。
            if db_path.is_file() and not db_added:
                _safe_add_db(zf, db_path, db_path.name)
    finally:
        _release_backup_operation(operation_lock)

    buf.seek(0)
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
    }
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers=headers,
    )


# ---------------------------------------------------------------------------
# 导入
# ---------------------------------------------------------------------------
async def import_backup(file: UploadFile) -> dict:
    """以事务语义应用已校验的备份，并在失败时自动回滚。"""
    filename = file.filename or ""
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="仅支持 .zip 格式的备份包")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="上传的备份包为空")
    if len(content) > MAX_IMPORT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"备份包过大（上限 {MAX_IMPORT_BYTES // (1024 * 1024)} MB），已拒绝",
        )

    data_dir: Path = config.DATA_DIR
    backup_path = data_dir.parent / f".backup-{_timestamp()}"
    stage_path: Path | None = None
    operation_lock: Path | None = None

    try:
        operation_lock = _claim_backup_operation(data_dir)
        with tempfile.TemporaryDirectory() as tmp_root:
            tmp_root_path = Path(tmp_root)
            zip_path = tmp_root_path / "upload.zip"
            zip_path.write_bytes(content)

            with zipfile.ZipFile(zip_path, "r") as zf:
                names = zf.namelist()
                _validate_member_names(names)
                infos = zf.infolist()
                if len(infos) > MAX_ARCHIVE_MEMBERS:
                    raise HTTPException(
                        status_code=413, detail="备份包文件数量过多，已拒绝导入")
                expanded = sum(max(0, info.file_size) for info in infos)
                if expanded > MAX_EXTRACT_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="备份包解压后超过 2GB 上限，已拒绝导入",
                    )

                bad = zf.testzip()
                if bad is not None:
                    raise HTTPException(
                        status_code=400,
                        detail=f"备份包已损坏（首个异常文件: {bad}）",
                    )

                if "manifest.json" not in names:
                    raise HTTPException(
                        status_code=400,
                        detail="备份包缺少 manifest.json，不是有效的 AI-Research-OS 备份",
                    )

                try:
                    manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
                except Exception:
                    raise HTTPException(
                        status_code=400, detail="manifest.json 解析失败，备份包无效"
                    )

                if manifest.get("app") != APP_NAME:
                    raise HTTPException(
                        status_code=400,
                        detail="manifest.json 标识异常（app != ai-research-os），拒绝导入",
                    )

                # 解压到临时目录，再做安全拷贝（避免直接解压到 DATA_DIR 时的 Zip Slip）。
                extract_dir = tmp_root_path / "extracted"
                zf.extractall(extract_dir)

            # 1）把每个候选文件复制到同一文件系统上的暂存目录。
            # 所有读取、空间或权限错误都必须在修改线上数据之前发生。
            data_dir.parent.mkdir(parents=True, exist_ok=True)
            stage_path = Path(
                tempfile.mkdtemp(prefix=".airos-import-stage-", dir=data_dir.parent)
            )
            staged: list[tuple[Path, Path, bool]] = []
            for item in sorted(extract_dir.rglob("*")):
                if not item.is_file():
                    continue
                rel = item.relative_to(extract_dir)
                top = rel.parts[0]
                if (
                    top in EXCLUDE_DIRS
                    or top == "manifest.json"
                    or top in EXCLUDE_FILES
                    or _is_excluded(rel, config.DB_PATH.name)
                ):
                    continue
                target, is_db = _import_target(data_dir, config.DB_PATH, rel)
                staged_file = stage_path / rel
                staged_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, staged_file)
                if is_db:
                    _validate_sqlite_file(staged_file)
                staged.append((staged_file, target, is_db))

            if not staged:
                raise HTTPException(status_code=400, detail="备份包不包含可导入的数据文件")

            # 2）应用任何内容之前，先快照当前完整状态。
            try:
                _snapshot_data_dir(data_dir, backup_path, config.DB_PATH)
            except (PermissionError, OSError, sqlite3.Error) as exc:
                shutil.rmtree(backup_path, ignore_errors=True)
                raise HTTPException(
                    status_code=500,
                    detail=f"备份当前数据失败（可能是数据库正被占用）：{exc}。请先停止应用再导入。",
                )

            # 3）逐个原子应用暂存文件；SQLite 使用 Online Backup API。
            # 任何失败都会恢复本次导入触及的所有目标，确保 API 操作具备原子语义。
            imported_entries = sorted(
                {staged_file.relative_to(stage_path).parts[0] for staged_file, _, _ in staged}
            )
            plan = [
                (
                    target,
                    staged_file.relative_to(stage_path),
                    is_db,
                    target.exists(),
                )
                for staged_file, target, is_db in staged
            ]
            journal_path = _write_import_journal(
                data_dir, backup_path, plan, state="applying"
            )
            applied: list[tuple[Path, Path, bool, bool]] = []
            try:
                for (staged_file, target, is_db), plan_item in zip(staged, plan):
                    # 应用前先记录目标，使部分失败的数据库备份也能被防御性恢复。
                    applied.append(plan_item)
                    if is_db:
                        _sqlite_snapshot(staged_file, target)
                    else:
                        _atomic_copy_file(staged_file, target)
                _write_import_journal(data_dir, backup_path, plan, state="committed")
            except Exception as exc:  # noqa: BLE001 - 回滚所有应用阶段的失败
                rollback_failures = _rollback_import(
                    applied, backup_path, config.DB_PATH.name
                )
                if rollback_failures:
                    raise HTTPException(
                        status_code=500,
                        detail=(
                            f"导入失败且自动回滚不完整：{exc}；"
                            f"回滚错误：{'；'.join(rollback_failures)}；"
                            f"完整快照保留在 {backup_path}"
                        ),
                    ) from exc
                journal_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=500,
                    detail=f"导入失败，已自动恢复原数据：{exc}",
                ) from exc
            # 已提交日志在崩溃后仍是安全的：启动时保留新数据并只删除标记，
            # 因此这里尽力清理即可。
            try:
                journal_path.unlink()
            except OSError:
                pass

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"导入过程中发生未知错误：{exc}"
        ) from exc
    finally:
        if stage_path is not None:
            shutil.rmtree(stage_path, ignore_errors=True)
        _release_backup_operation(operation_lock)

    return {
        "success": True,
        "message": "导入完成",
        "imported_entries": imported_entries,
        "backup_path": str(backup_path),
        "note": "所有文件已成功应用，并保留导入前一致性快照。",
    }


__all__ = ["router"]
