"""Obsidian integration routes.

Lightweight subprocess calls to ``scripts/obsidian_service.py``
(``list_vaults`` / ``add_vault`` / ``scan`` / ``list_files`` / ``get_content``).

The current ``space_id`` is resolved per request and forwarded to the subprocess
via the ``SPACE_ID`` environment variable so vault metadata stays isolated.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..deps import get_space_id
from ..helpers import run_script

router = APIRouter(prefix="/api/obsidian", tags=["obsidian"])


class VaultCreate(BaseModel):
    name: str
    path: str


@router.get("/vaults")
async def list_vaults(space_id: str = Depends(get_space_id)):
    return run_script("obsidian_service.py", "list_vaults", env_extra={"SPACE_ID": space_id})


@router.post("/vaults")
async def add_vault(req: VaultCreate, space_id: str = Depends(get_space_id)):
    return run_script(
        "obsidian_service.py", "add_vault", req.name, req.path, env_extra={"SPACE_ID": space_id}
    )


@router.post("/vaults/{vault_id}/scan")
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
