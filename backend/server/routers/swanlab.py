"""SwanLab integration routes.

Kept as lightweight subprocess calls to ``scripts/swanlab_api.py`` (per the
agreed decision) rather than refactored into importable functions.  The script
prints a JSON object which ``run_script`` parses and forwards to the client.
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from ..helpers import run_script

router = APIRouter(prefix="/api/swanlab", tags=["swanlab"])


class SwanlabConfig(BaseModel):
    apiKey: str = ""
    apiUrl: str = "https://api.swanlab.cn/api"
    enabled: bool = True
    defaultWorkspace: Optional[str] = None


class SwanlabTest(BaseModel):
    apiKey: Optional[str] = None
    apiUrl: str = "https://api.swanlab.cn/api"


@router.get("/config")
async def get_config():
    return run_script("swanlab_api.py", "get_config", json.dumps({}))


@router.post("/config")
async def save_config(req: SwanlabConfig):
    return run_script("swanlab_api.py", "save_config", json.dumps(req.model_dump()))


@router.post("/test")
async def test_connection(req: SwanlabTest):
    return run_script("swanlab_api.py", "test_connection", json.dumps(req.model_dump()))


@router.post("/fetch")
async def fetch_data():
    return run_script("swanlab_api.py", "fetch_data", json.dumps({}))


@router.get("/workspaces")
async def list_workspaces():
    return run_script("swanlab_api.py", "list_workspaces")


@router.get("/projects")
async def list_projects():
    return run_script("swanlab_api.py", "list_projects", json.dumps({}))


@router.get("/experiments")
async def list_experiments(project: str = ""):
    return run_script("swanlab_api.py", "list_experiments", json.dumps({"project": project}))


@router.get("/experiment/detail")
async def experiment_detail(project: str = "", expId: str = ""):
    return run_script(
        "swanlab_api.py",
        "get_experiment_detail",
        json.dumps({"project": project, "expId": expId}),
    )


@router.get("/cache")
async def get_cache():
    return run_script("swanlab_api.py", "get_cached_data")


@router.get("/status")
async def check_status():
    return run_script("swanlab_api.py", "check_status")


__all__ = ["router"]
