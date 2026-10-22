"""A bare page with one ui.context_editor, for browser tests. Env: PORT, HARNESS_HTML (file), HARNESS_READONLY."""
from __future__ import annotations

import os
from pathlib import Path

from nicegui import ui

import ctxeditor.web.editor  # noqa: F401  (registers ui.context_editor and the static fonts)

HTML = Path(os.environ["HARNESS_HTML"]).read_text() if os.environ.get("HARNESS_HTML") else ""
READONLY = os.environ.get("HARNESS_READONLY") == "1"
COMMENTING = os.environ.get("HARNESS_COMMENTING") == "1"
EVENTS: list = []


@ui.page("/")
def index():
    ui.add_head_html("<style>html,body{height:100%;margin:0}.nicegui-content{padding:0;height:100vh}</style>")
    editor = ui.context_editor(value=HTML, readonly=READONLY, commenting=COMMENTING).classes("h-full").mark("editor")
    editor.on_event("save", lambda e: ui.run_javascript("window.__saved = (window.__saved||0)+1"))


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(port=int(os.environ["PORT"]), reload=False, show=False, storage_secret="harness", title="harness")
