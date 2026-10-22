"""NiceGUI composition for the standalone editor app."""
from __future__ import annotations

from nicegui import app

from .context import AppContext
from .layout import apply_theme
from .pages import workspace


def create_app(ctx: AppContext) -> None:
    apply_theme()
    workspace.register(ctx)
    app.on_shutdown(ctx.exporter.pool.close)
