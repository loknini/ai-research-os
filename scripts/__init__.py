"""Shared backend scripts package.

Houses the async SQLite layer (``database``), the arXiv fetcher (``fetch_arxiv``),
the chat/agent streaming helpers (``chat_agent_stream``), the paper summarizer
(``summarize_paper``) and the various service adapters. Import them with absolute
package paths:

    from scripts import database
    from scripts import fetch_arxiv
    from scripts.chat_agent_stream import execute_tool

They are first-class package submodules (this ``__init__.py`` makes ``scripts`` a
package), so the backend and the QA scripts share the *same* module objects and
bare intra-package imports resolve to siblings automatically.
"""
