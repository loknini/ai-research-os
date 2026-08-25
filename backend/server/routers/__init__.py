"""Aggregate all API routers for the FastAPI app."""
from .agent import router as agent_router
from .chat import router as chat_router
from .citation import router as citation_router
from .conversations import router as conversations_router
from .cron import router as cron_router
from .experiments import router as experiments_router
from .formula import router as formula_router
from ..health import router as health_router
from .notes import router as notes_router
from .obsidian import router as obsidian_router
from .papers import router as papers_router
from .projects import router as projects_router
from .search import router as search_router
from .settings import router as settings_router
from .skills import router as skills_router
from .swanlab import router as swanlab_router
from .backup import router as backup_router
from .tasks import router as tasks_router
from .memory import router as memory_router
from .versions import router as versions_router
from .rag import router as rag_router

routers = [
    health_router,
    search_router,
    agent_router,
    chat_router,
    papers_router,
    tasks_router,
    projects_router,
    notes_router,
    experiments_router,
    conversations_router,
    versions_router,
    cron_router,
    settings_router,
    skills_router,
    swanlab_router,
    backup_router,
    formula_router,
    citation_router,
    obsidian_router,
    memory_router,
    rag_router,
]

__all__ = ["routers"]
