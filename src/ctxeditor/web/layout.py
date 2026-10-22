"""Shared theme and helpers for the workspace page. One accent colour, a neutral palette, Inter for the interface.
The Quasar defaults are overridden here so the app does not look like a stock Quasar page."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from nicegui import ui

from .editor import STATIC_URL

ACCENT = "#4f6bed"
FAILED = object()  # returned by Workspace.call when an operation raised a (already reported) error

CSS = """
:root { --ws-bg:#f6f7f9; --ws-surface:#ffffff; --ws-text:#1f2430; --ws-muted:#6b7280; --ws-border:#e3e6ec;
        --ws-accent:#4f6bed; --ws-accent-soft:rgba(79,107,237,.12); --ws-danger:#c62828; --ws-ok:#19734f; --ws-warn:#9a6700; }
body.body--dark { --ws-bg:#101218; --ws-surface:#16181f; --ws-text:#e6e8ee; --ws-muted:#98a1b3; --ws-border:#2d313c;
        --ws-accent:#7d93ff; --ws-accent-soft:rgba(125,147,255,.18); --ws-danger:#ff8a8a; --ws-ok:#5fd3a2; --ws-warn:#e3b341; }
html, body { font-family:"Inter", system-ui, -apple-system, "Segoe UI", sans-serif; background:var(--ws-bg); color:var(--ws-text); }
.q-layout, .q-page, .q-drawer, .q-header, .q-card, .q-menu, .q-dialog__inner > div { font-family:inherit; }
.q-header.ws-header { background:var(--ws-surface); color:var(--ws-text); border-bottom:1px solid var(--ws-border); box-shadow:none; }
.q-drawer.ws-drawer { background:var(--ws-surface); }
.q-drawer--bordered { border-color:var(--ws-border) !important; }
.ws-brand { font-weight:650; letter-spacing:-.01em; font-size:15px; }
.ws-muted { color:var(--ws-muted); }
.ws-section-title { font-size:11px; font-weight:650; letter-spacing:.07em; text-transform:uppercase; color:var(--ws-muted); }
.ws-doc-item { border-radius:10px; padding:8px 10px; cursor:pointer; transition:background .12s; }
.ws-doc-item:hover { background:var(--ws-bg); }
.ws-doc-item.is-active { background:var(--ws-accent-soft); }
.ws-doc-title { font-size:13.5px; font-weight:550; line-height:1.3; }
.ws-badge { font-size:10.5px; font-weight:650; letter-spacing:.03em; padding:2px 8px; border-radius:999px; border:1px solid var(--ws-border); color:var(--ws-muted); background:transparent; }
.ws-badge.draft { color:var(--ws-warn); border-color:currentColor; }
.ws-badge.published { color:var(--ws-ok); border-color:currentColor; }
.ws-badge.role { color:var(--ws-accent); border-color:currentColor; }
.ws-card { background:var(--ws-surface); border:1px solid var(--ws-border); border-radius:14px; box-shadow:none; }
.ws-meta { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:10px 24px; font-size:12.5px; }
.ws-meta dt { color:var(--ws-muted); font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:.05em; }
.ws-meta dd { margin:2px 0 0; font-weight:500; }
.ws-title { font-size:22px; font-weight:650; letter-spacing:-.02em; line-height:1.25; }
.ws-banner { border-radius:10px; padding:8px 12px; font-size:13px; border:1px solid var(--ws-border); background:var(--ws-surface); }
.ws-banner.warn { border-color:var(--ws-warn); }
.ws-banner.error { border-color:var(--ws-danger); }
.ws-banner.info { border-color:var(--ws-accent); }
.ws-dirty { width:8px; height:8px; border-radius:50%; background:var(--ws-warn); display:inline-block; }
.ws-editor-shell { background:var(--ws-surface); border:1px solid var(--ws-border); border-radius:14px; overflow:hidden; height:calc(100vh - 290px); min-height:420px; }
.ws-comment { border:1px solid var(--ws-border); border-radius:12px; padding:10px 12px; background:var(--ws-surface); cursor:pointer; }
.ws-comment.is-resolved { opacity:.72; }
.ws-quote { font-size:12.5px; font-style:italic; color:var(--ws-muted); border-left:3px solid var(--ws-accent); padding-left:8px; }
.ws-reply { border-left:2px solid var(--ws-border); margin-left:6px; padding-left:10px; }
.ws-bubble-user { background:var(--ws-accent-soft); border-radius:12px 12px 2px 12px; padding:8px 12px; font-size:13.5px; align-self:flex-end; max-width:92%; }
.ws-bubble-agent { background:var(--ws-bg); border:1px solid var(--ws-border); border-radius:12px 12px 12px 2px; padding:8px 12px; font-size:13.5px; max-width:92%; }
.ws-empty { text-align:center; color:var(--ws-muted); padding:28px 12px; font-size:13.5px; }
.q-btn { text-transform:none; }
.q-tab { text-transform:none; font-weight:550; }
.q-field--outlined .q-field__control { border-radius:10px; }
@media (max-width: 1100px) { .ws-editor-shell { height:calc(100vh - 250px); } }
@media (prefers-reduced-motion: reduce) { * { transition:none !important; } }
"""


def apply_theme() -> None:
    """Process-wide widget defaults. Call once when the app is composed."""
    ui.add_head_html(f'<link rel="stylesheet" href="{STATIC_URL}/fonts.css"><style>{CSS}</style>', shared=True)
    for widget in (ui.input, ui.textarea, ui.select):
        widget.default_classes("w-full")
        widget.default_props("outlined dense")


def page_colors() -> None:
    """Quasar brand colours. Call inside a page function."""
    ui.colors(primary=ACCENT, secondary="#6b7280", accent=ACCENT, positive="#19734f", negative="#c62828",
              warning="#9a6700", info=ACCENT)


def icon_button(icon: str, label: str, on_click=None, *, color: str | None = None, flat: bool = True,
                size: str = "md") -> ui.button:
    """Icon-only button with an accessible name and a tooltip (AGENTS.md: grouped buttons are icon buttons)."""
    button = ui.button(icon=icon, on_click=on_click).props(
        f'{"flat " if flat else ""}round dense size={size} aria-label="{label}"'
        + (f" color={color}" if color else ""))
    with button:
        ui.tooltip(label)
    return button


@asynccontextmanager
async def busy(*buttons: ui.button) -> AsyncIterator[None]:
    """Show a spinner on the buttons and disable them for the whole operation (AGENTS.md)."""
    for b in buttons:
        b.props(add="loading")
        b.disable()
    try:
        yield
    finally:
        for b in buttons:
            b.props(remove="loading")
            b.enable()
