"""AI-Research-OS FastAPI 后端包。

模块统一通过正规包路径导入；这里有意不修改 ``sys.path``，旧的路径注入方案已于
2026-07-31 删除：

    from scripts import database                       # 顶层 ``scripts/`` 包
    from scripts import fetch_arxiv
    from scripts.chat_agent_stream import execute_tool
    from .agents import service                        # Agent 领域包
    from . import db                                   # backend/server 子模块
    from backend.server.llm import llm_client          # 跨子模块绝对导入

Agent 实现位于 ``backend/server/agents/``，RAG 实现位于 ``backend/server/rag/``，
配置与生命周期位于 ``backend/server/core/``。历史 ``backend/scripts/`` 和根级兼容
模块均已删除，避免同名遮蔽与双入口。``backend`` 和 ``scripts`` 都是正规 Python 包，
因此包内相对导入与跨包绝对导入均可稳定工作。
"""
__all__: list[str] = []
