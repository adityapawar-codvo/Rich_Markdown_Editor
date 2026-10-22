"""Run the demo: ``uv run context-editor``. Creates and seeds the database on first start."""
from __future__ import annotations

import os

from dotenv import load_dotenv
from nicegui import ui

from .db import Database
from .migrate import migrate
from .seed import seed
from .web.app import create_app
from .web.context import build_context


def prepare(db_path: str) -> Database:
    db = Database(db_path)
    migrate(db)
    with db.read() as conn:
        empty = conn.execute("select count(*) n from tenants").fetchone()["n"] == 0
    if empty:
        seed(db)
    return db


def run() -> None:
    load_dotenv()
    db = prepare(os.environ.get("CONTEXT_EDITOR_DB", "context_editor_demo.db"))
    create_app(build_context(db))
    ui.run(title="Context Editor", port=int(os.environ.get("PORT", "8080")), reload=False, show=False,
           storage_secret=os.environ.get("NICEGUI_STORAGE_SECRET", "dev-only-change-me"))


if __name__ in {"__main__", "__mp_main__"}:
    run()
