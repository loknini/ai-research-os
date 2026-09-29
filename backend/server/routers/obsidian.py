"""Obsidian 集成路由。

通过轻量子进程调用 ``scripts/obsidian_service.py`` 的 Vault 列表、添加、扫描、文件
列表和内容读取操作。每个请求都会解析当前 ``space_id``，再通过 ``SPACE_ID`` 环境
变量传给子进程，使 Vault 元数据保持空间隔离。
"""
from __future__ import annotations

import os
import string
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from ..core.admin_access import require_admin
from ..deps import get_space_id
from ..helpers import run_script

router = APIRouter(prefix="/api/obsidian", tags=["obsidian"])


class VaultCreate(BaseModel):
    name: str
    path: str


def _directory_entry(path: Path) -> dict:
    """返回服务端目录选择器所需的安全元数据。"""
    try:
        is_vault = (path / ".obsidian").is_dir()
    except OSError:
        is_vault = False
    return {
        "name": path.name or path.anchor or str(path),
        "path": str(path),
        "isVault": is_vault,
    }


def _filesystem_roots() -> list[Path]:
    if os.name == "nt":
        return [Path(f"{letter}:\\") for letter in string.ascii_uppercase if Path(f"{letter}:\\").is_dir()]
    return [Path("/")]


def _resolve_directory(raw_path: str) -> Path:
    try:
        path = Path(raw_path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="目录不存在或不可访问") from exc
    if not path.is_dir():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="所选路径不是目录")
    return path


@router.get("/directories", dependencies=[Depends(require_admin)])
async def browse_directories(path: str | None = Query(default=None)):
    """浏览后端进程可见的目录。

    这是部署级文件系统能力，不属于空间数据；本机请求可直接使用，远程调用方必须
    提供 ``X-Admin-Token``。
    """
    if path is None or not path.strip():
        return {
            "success": True,
            "currentPath": None,
            "parentPath": None,
            "directories": [_directory_entry(root) for root in _filesystem_roots()],
        }

    current = _resolve_directory(path)
    directories: list[dict] = []
    try:
        children = sorted(current.iterdir(), key=lambda item: item.name.casefold())
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="没有权限读取该目录") from exc
    except OSError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无法读取该目录") from exc

    for child in children:
        try:
            if child.is_dir():
                directories.append(_directory_entry(child.resolve(strict=True)))
        except (OSError, RuntimeError):
            # 单个不可访问或损坏的目录项不应导致整个父目录列表失败。
            continue

    parent = current.parent if current.parent != current else None
    return {
        "success": True,
        "currentPath": str(current),
        "parentPath": str(parent) if parent is not None else None,
        "directories": directories,
    }


@router.get("/vaults")
async def list_vaults(space_id: str = Depends(get_space_id)):
    return run_script("obsidian_service.py", "list_vaults", env_extra={"SPACE_ID": space_id})


@router.post("/vaults", dependencies=[Depends(require_admin)])
async def add_vault(req: VaultCreate, space_id: str = Depends(get_space_id)):
    return run_script(
        "obsidian_service.py", "add_vault", req.name, req.path, env_extra={"SPACE_ID": space_id}
    )


@router.post("/vaults/{vault_id}/scan", dependencies=[Depends(require_admin)])
async def scan_vault(vault_id: int, space_id: str = Depends(get_space_id)):
    return run_script(
        "obsidian_service.py", "scan", str(vault_id), env_extra={"SPACE_ID": space_id}
    )


@router.get("/vaults/{vault_id}/files")
async def list_files(vault_id: int, space_id: str = Depends(get_space_id)):
    return run_script(
        "obsidian_service.py", "list_files", str(vault_id), env_extra={"SPACE_ID": space_id}
    )


@router.get("/files/{file_id}")
async def get_file(file_id: int, space_id: str = Depends(get_space_id)):
    return run_script(
        "obsidian_service.py", "get_content", str(file_id), env_extra={"SPACE_ID": space_id}
    )


__all__ = ["router"]
