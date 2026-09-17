"""Backup export / import routes for AI-Research-OS.

Two endpoints, both mounted under ``/api/backup``:

* ``POST /api/backup/export``
    Bundle the whole ``DATA_DIR`` into a zip (in memory) and stream it back.
    Junk / cache directories (``.git`` / ``.openclaw`` / ``.swanlab`` /
    ``.cache`` / ``__pycache__``) are excluded, and a ``manifest.json`` is
    placed at the zip root describing the package.
* ``POST /api/backup/import``
    Accept an ``UploadFile`` (field ``file``, ``.zip`` only, 500 MB cap),
    validate its manifest, back up the *current* ``DATA_DIR`` to a sibling
    ``.backup-<timestamp>`` directory, then overwrite ``DATA_DIR`` with the
    zip contents.  SQLite may be locked while the app runs — failures are
    caught and reported via the JSON ``note`` rather than crashing.

Only the standard library (``zipfile`` / ``shutil`` / ``tempfile``) is used;
no new dependency beyond ``python-multipart`` (needed for ``UploadFile``).
"""
from __future__ import annotations

import io
import json
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from .. import config

router = APIRouter(prefix="/api/backup", tags=["backup"])

APP_NAME = "ai-research-os"
MANIFEST_VERSION = "0.1"

# Directories excluded from both export and import (junk / cache / internal).
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
    # Runtime coordination state: it is regenerated on startup and may be
    # concurrently replaced by the instance heartbeat writer on Windows.
    ".backend_supervisors.json",
    ".backend_supervisors.json.tmp",
    ".backend_supervisors.lock",
}

# Hard cap on uploaded backup size to prevent abuse (500 MB).
MAX_IMPORT_BYTES = 500 * 1024 * 1024
MAX_EXTRACT_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 100_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _utcnow_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _timestamp() -> str:
    """Filesystem-friendly local timestamp ``YYYYMMDD-HHMMSS``."""
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _top_entries(data_dir: Path) -> List[str]:
    """Sorted list of top-level entry names inside ``DATA_DIR`` (junk excluded)."""
    return sorted(
        p.name
        for p in data_dir.iterdir()
        if not _is_excluded(Path(p.name), config.DB_PATH.name)
    )


def _is_excluded(rel: Path, db_name: str) -> bool:
    """Return whether a DATA_DIR-relative path is runtime/cache state."""
    if any(part in EXCLUDE_DIRS for part in rel.parts):
        return True
    if rel.name in EXCLUDE_FILES:
        return True
    if rel.name in {f"{db_name}-wal", f"{db_name}-shm", f"{db_name}-journal"}:
        return True
    # Defensive: an export implementation may later switch from an in-memory
    # buffer to a file under DATA_DIR. Never recursively archive that output.
    return rel.name.startswith("airos-backup-") and rel.suffix.lower() == ".zip"


def _sqlite_snapshot(source: Path, destination: Path) -> None:
    """Create a transactionally consistent SQLite snapshot.

    Copying only the main file of a live WAL database can silently omit recent
    commits. SQLite's Online Backup API reads the main DB and WAL coherently.
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
    """Add a consistent SQLite snapshot to the archive."""
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
    """Back up current data without copying locks, WAL files, or live DB bytes."""
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
    """Reject zip entries that try to escape the extraction root (Zip Slip)."""
    for name in names:
        normalized = name.replace("\\", "/")
        parts = normalized.split("/")
        if ("\x00" in normalized or normalized.startswith("/") or ".." in parts
                or (parts and ":" in parts[0])):
            raise HTTPException(
                status_code=400, detail="备份包包含非法路径，已拒绝导入"
            )


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
@router.post("/export")
async def export_backup() -> StreamingResponse:
    """Stream a zip of ``DATA_DIR`` (junk excluded) with a ``manifest.json``."""
    data_dir: Path = config.DATA_DIR
    if not data_dir.exists():
        raise HTTPException(status_code=404, detail="数据目录不存在，无法导出备份")

    db_path: Path = config.DB_PATH
    filename = f"airos-backup-{_timestamp()}.zip"

    buf = io.BytesIO()
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

        # DB_PATH may intentionally live outside DATA_DIR. It still belongs in
        # a portable backup, at the manifest-declared root name.
        if db_path.is_file() and not db_added:
            _safe_add_db(zf, db_path, db_path.name)

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
# Import
# ---------------------------------------------------------------------------
@router.post("/import")
async def import_backup(file: UploadFile = File(...)) -> dict:
    """Import a ``.zip`` backup, backing up the current data first.

    Returns JSON ``{success, message, imported_entries, backup_path, note}``.
    A locked SQLite file (app still running) is reported via ``note`` instead
    of raising, so the operator knows to restart the app to load new data.
    """
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

    try:
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

            # 1) 先备份当前数据（避免覆盖丢失）
            try:
                _snapshot_data_dir(data_dir, backup_path, config.DB_PATH)
            except (PermissionError, OSError, sqlite3.Error) as exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"备份当前数据失败（可能是数据库正被占用）：{exc}。请先停止应用再导入。",
                )

            # 2) 用临时目录内容覆盖 DATA_DIR（剔除垃圾目录、manifest.json 与 OpenClaw 遗留文件）
            imported_entries = sorted(
                {
                    n.split("/")[0]
                    for n in names
                    if n.split("/")[0]
                    and n.split("/")[0] not in EXCLUDE_DIRS
                    and n.split("/")[0] != "manifest.json"
                    and n.split("/")[0] not in EXCLUDE_FILES
                    and not _is_excluded(Path(n), config.DB_PATH.name)
                }
            )
            db_write_failed = False
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
                is_db = top == config.DB_PATH.name and len(rel.parts) == 1
                target = config.DB_PATH if is_db else data_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    if is_db:
                        _sqlite_snapshot(item, target)
                    else:
                        shutil.copyfile(item, target)
                except (PermissionError, OSError, sqlite3.Error):
                    if is_db:
                        db_write_failed = True
                    # 非数据库文件失败仅跳过，不阻断整体导入

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"导入过程中发生未知错误：{exc}"
        ) from exc

    note = (
        "导入完成，已用备份包覆盖当前数据目录。"
        if not db_write_failed
        else "数据库文件写入失败（可能被正在运行的应用占用）。请停止 app 后重启以加载新数据。"
    )
    return {
        "success": True,
        "message": "导入完成" if not db_write_failed else "导入完成（数据库需重启后生效）",
        "imported_entries": imported_entries,
        "backup_path": str(backup_path),
        "note": note,
    }


__all__ = ["router"]
