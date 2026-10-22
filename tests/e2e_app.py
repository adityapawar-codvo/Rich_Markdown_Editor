"""The real app on a throwaway database with a fake model client, for end-to-end browser tests.
Env: PORT, E2E_DB."""
from __future__ import annotations

import os
import re

from nicegui import ui

from ctxeditor.agent.openrouter import LlmResult
from ctxeditor.agent.settings import AgentSettings, Secret
from ctxeditor.__main__ import prepare
from ctxeditor.web.app import create_app
from ctxeditor.web.context import build_context


class FakeModel:
    """Appends one paragraph and rewrites the title, so the diff has an added and a modified hunk."""

    async def complete(self, system: str, user: str) -> LlmResult:
        doc = re.search(r"<document>\n(.*)\n</document>", user, re.S).group(1)
        doc = doc.replace("<h1>", "<h1>Revised: ", 1)
        return LlmResult(text=doc + "<p>Added by the assistant.</p>", tokens_in=10, tokens_out=10)


if __name__ in {"__main__", "__mp_main__"}:
    db = prepare(os.environ["E2E_DB"])
    settings = AgentSettings(api_key=Secret("sk-or-v1-TESTKEY123"))
    create_app(build_context(db, settings=settings, client=FakeModel()))
    ui.run(port=int(os.environ["PORT"]), reload=False, show=False, storage_secret="e2e", title="e2e")
