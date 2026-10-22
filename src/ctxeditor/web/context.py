"""The services the pages use, composed once at start-up."""
from __future__ import annotations

from dataclasses import dataclass

from ..agent.openrouter import OpenRouterClient
from ..agent.service import AgentClient, AgentService
from ..agent.settings import AgentSettings
from ..authz import AuthzService
from ..comments import CommentService
from ..db import Database
from ..documents import DocumentService
from ..export.browser import BrowserPool
from ..export.service import ExportService


@dataclass
class AppContext:
    db: Database
    authz: AuthzService
    docs: DocumentService
    comments: CommentService
    agent: AgentService
    exporter: ExportService


def build_context(db: Database, *, settings: AgentSettings | None = None, client: AgentClient | None = None,
                  pool: BrowserPool | None = None) -> AppContext:
    settings = settings or AgentSettings.from_env()
    authz = AuthzService(db)
    docs = DocumentService(db, authz)
    comments = CommentService(db, authz, docs)
    agent = AgentService(db, authz, docs, comments, client or OpenRouterClient(settings), settings)
    return AppContext(db, authz, docs, comments, agent, ExportService(docs, pool))
