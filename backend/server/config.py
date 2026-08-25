"""Application configuration for the AI-Research-OS FastAPI backend.

Reads settings from environment variables / ``.env`` files and exposes a
single ``settings`` instance plus resolved DB paths.

Critical detail: ``os.environ['DATA_DIR']`` is set *before* ``scripts/database.py``
is imported so the SQLite path stays consistent between this backend and the
legacy scripts (which read ``DATA_DIR`` at import time).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = parent of ``backend/`` (i.e. the ai-research-os directory).
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"

# Load both the project-root .env and backend/.env (if present) into the
# environment so that pydantic-settings can pick them up.  Manual loading keeps
# us independent of which file the operator chose to create.
for _env_candidate in (PROJECT_ROOT / ".env", PROJECT_ROOT / "backend" / ".env"):
    if _env_candidate.exists():
        load_dotenv(dotenv_path=str(_env_candidate), override=False)


# 兼容性补丁：旧配置把 /v1 同时写在 BASE_URL 和 HTTP_PATH 里，会导致路径重复。
# 检测到这种冲突时，自动将 HTTP_PATH 降级为 /chat/completions（仅影响本次运行时的内存配置）。
_old_base = (os.environ.get("LLM_BASE_URL") or "").rstrip("/")
_old_path = os.environ.get("LLM_HTTP_PATH") or ""
if _old_base.endswith("/v1") and _old_path.startswith("/v1/"):
    os.environ["LLM_HTTP_PATH"] = _old_path[len("/v1"):]


class Settings(BaseSettings):
    """Runtime configuration loaded from the environment."""

    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- LLM (OpenAI-compatible) ----
    # 默认留空：启动后请在「设置 → LLM API 配置」中填写（硅基流动 / 智谱 / Ollama 等）。
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_temperature: float = 0.7
    llm_max_tokens: int = 4000
    llm_timeout: int = 120
    # 默认 path 不包含 /v1：Base URL 本身应包含 /v1（OpenAI SDK 风格）。
    # 示例：Base URL = https://api.siliconflow.cn/v1，最终 endpoint = .../v1/chat/completions。
    llm_http_path: str = "/chat/completions"
    # 嵌入模型（RAG 向量检索用）。留空时回退到 llm_model；多数服务二者不同
    # （如 SiliconFlow 用 BAAI/bge-m3，OpenAI 用 text-embedding-3-small）。
    llm_embed_model: str = ""

    # ---- Database ----
    db_path: Optional[str] = None
    data_dir: Optional[str] = None

    # ---- Server ----
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    cors_origins: str = "*"

    @property
    def resolved_data_dir(self) -> Path:
        if self.data_dir:
            return Path(self.data_dir)
        return DEFAULT_DATA_DIR

    @property
    def resolved_db_path(self) -> Path:
        if self.db_path:
            return Path(self.db_path)
        return self.resolved_data_dir / "ai_research_os.db"


# Instantiate singleton.
settings = Settings()

# Ensure the data directory exists and export it to the environment *before*
# any script (notably ``scripts/database.py``) is imported.
_RESOLVED_DIR = settings.resolved_data_dir
_RESOLVED_DIR.mkdir(parents=True, exist_ok=True)
os.environ["DATA_DIR"] = str(_RESOLVED_DIR)
if settings.db_path:
    os.environ["DB_PATH"] = str(settings.resolved_db_path)

# Convenience exports used across the app.
DATA_DIR: Path = _RESOLVED_DIR
DB_PATH: Path = settings.resolved_db_path
SCRIPTS_DIR: Path = PROJECT_ROOT / "scripts"


def get_cors_origins() -> List[str]:
    """Parse CORS origins.

    ``*`` (the dev default) means allow all origins.
    """
    if not settings.cors_origins or settings.cors_origins.strip() == "*":
        return ["*"]
    return [o.strip() for o in settings.cors_origins.split(",") if o.strip()]


__all__ = [
    "settings",
    "DATA_DIR",
    "DB_PATH",
    "SCRIPTS_DIR",
    "PROJECT_ROOT",
    "get_cors_origins",
]
