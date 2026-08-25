"""AI-Research-OS FastAPI backend package.

Modules import via **regular package paths** — there is intentionally **no
``sys.path`` manipulation** here (the old ``sys.path``-injection hack was removed
on 2026-07-31):

    from scripts import database                       # top-level ``scripts/`` package
    from scripts import fetch_arxiv
    from scripts.chat_agent_stream import execute_tool
    from . import agent_service, db                    # backend/server submodules
    from backend.server.llm import llm_client          # cross-submodule (absolute)

``agent_service`` lives at ``backend/server/agent_service.py`` (same package as
``agent_runner`` / ``db``); the old ``backend/scripts/`` directory was deleted to
eliminate the same-named-package shadowing problem. ``backend`` and ``scripts`` are
both proper packages (each has ``__init__.py``), so both ``from . import x`` and
``from .. import x`` work.
"""
__all__: list[str] = []
