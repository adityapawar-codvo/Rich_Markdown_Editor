"""ui.context_editor: a TipTap v3 document editor wrapped as a NiceGUI element.

Same component/esm mechanism NiceGUI uses for ui.codemirror. The JavaScript (TipTap, Mermaid, Chart.js) is bundled
locally with npm and rollup into dist/ (see package.json and rollup.config.mjs); nothing loads from a CDN at runtime.

The value is sanitized HTML. The browser owns the text while the user types; the server learns the new value on a
500 ms debounce, on save, or when asked with `await editor.get_html()`. Read-only is a convenience: the server
checks the caller's actions before every save.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from nicegui import app, ui
from nicegui.elements.mixins.value_element import ValueElement
from nicegui.events import Handler, ValueChangeEventArguments, handle_event

HERE = Path(__file__).resolve().parent
STATIC_DIR = HERE.parent / "static"
DIST_DIR = HERE / "dist"
DOCUMENT_CSS = DIST_DIR / "document.css"
STATIC_URL = "/_ctxeditor"

_registered = False


def register_static() -> None:
    """Serve the self-hosted fonts at /_ctxeditor. Safe to call more than once."""
    global _registered
    if not _registered:
        app.add_static_files(STATIC_URL, str(STATIC_DIR))
        _registered = True


register_static()


class ContextEditor(ValueElement[str],
                    component='context_editor.js',
                    esm={'context-editor-bundle': 'dist'},
                    default_classes='w-full h-full'):
    VALUE_PROP = 'value'
    LOOPBACK = None  # the browser owns the text while typing; the server only learns the new value

    def __init__(self, value: str = '', *,
                 readonly: bool = False,
                 commenting: bool = False,
                 theme: Literal['auto', 'light', 'dark'] = 'auto',
                 placeholder: str = 'Write, or type / for commands',
                 on_change: Handler[ValueChangeEventArguments[str]] | None = None,
                 on_save: Handler | None = None,
                 on_dirty: Handler | None = None,
                 on_selection_comment: Handler | None = None,
                 on_comment_click: Handler | None = None,
                 on_anchors_resolved: Handler | None = None,
                 on_hunk_decision: Handler | None = None,
                 on_diff_ready: Handler | None = None) -> None:
        """Context editor

        :param value: HTML, two-way bound
        :param readonly: when true the document cannot be edited in the browser
        :param commenting: when true, selecting text offers a comment button (works in read-only mode)
        :param theme: ``auto`` follows the NiceGUI dark mode
        :param on_change: called with the new HTML on a 500 ms debounce after edits
        :param on_save: Cmd/Ctrl+S inside the editor
        :param on_dirty: called with True/False when the document starts or stops differing from the last saved state
        :param on_selection_comment: called with ``{quote, prefix, suffix, hint}`` when the comment button is used
        :param on_comment_click: called with the anchor id of a clicked highlight
        :param on_anchors_resolved: called with ``{anchor_id: bool}``; False means the text is no longer present
        :param on_hunk_decision: diff view: ``{id, decision}`` with decision accepted | rejected | pending
        :param on_diff_ready: diff view: ``{invalid: [hunk ids], hunks: [hunk ids]}``
        """
        super().__init__(value=value, on_value_change=on_change)
        self._props['readonly'] = readonly
        self._props['commenting'] = commenting
        self._props['guard'] = False
        self._props['theme'] = theme
        self._props['placeholder'] = placeholder
        self.dirty = False
        self._handlers: dict[str, list[Handler]] = {}
        self._wire('save', on_save)
        self._wire('dirty', on_dirty, self._track_dirty)
        self._wire('selection_comment', on_selection_comment)
        self._wire('comment_click', on_comment_click)
        self._wire('anchors_resolved', on_anchors_resolved)
        self._wire('hunk_decision', on_hunk_decision)
        self._wire('diff_ready', on_diff_ready)

    def _wire(self, name: str, handler: Handler | None, internal: Handler | None = None) -> None:
        handlers = self._handlers.setdefault(name, [])
        if internal is not None:
            handlers.append(internal)
        if handler is not None:
            handlers.append(handler)

        def dispatch(event, name=name):
            for h in self._handlers[name]:
                handle_event(h, event)

        self.on(name, dispatch, args=None if name == 'save' else [None])

    def _track_dirty(self, event) -> None:
        self.dirty = bool(event.args)

    def on_event(self, name: str, handler: Handler) -> ContextEditor:
        """Add a handler for save, dirty, selection_comment, comment_click, anchors_resolved, hunk_decision
        or diff_ready."""
        self._handlers[name].append(handler)
        return self

    @property
    def readonly(self) -> bool:
        return bool(self._props['readonly'])

    @readonly.setter
    def readonly(self, value: bool) -> None:
        if self._props['readonly'] != value:
            self._props['readonly'] = value
            self.update()

    @property
    def commenting(self) -> bool:
        return bool(self._props['commenting'])

    @commenting.setter
    def commenting(self, value: bool) -> None:
        if self._props['commenting'] != value:
            self._props['commenting'] = value
            self.update()

    @property
    def guard(self) -> bool:
        return bool(self._props['guard'])

    @guard.setter
    def guard(self, value: bool) -> None:
        """True while unsaved edits are held aside on the server: the browser then warns before the page closes."""
        if self._props['guard'] != value:
            self._props['guard'] = value
            self.update()

    async def get_html(self) -> str:
        """The editor's current HTML (use this on save: it is never behind the debounce)."""
        return await self.run_method('getHTML')

    def mark_clean(self) -> None:
        """Call after a successful save so the unsaved indicator resets."""
        self.run_method('markClean')

    def focus(self) -> None:
        self.run_method('focus')

    def set_comment_anchors(self, anchors: list[dict[str, Any]]) -> None:
        """anchors: ``[{id, quote, prefix, suffix, hint, status}]``. Highlights are drawn as decorations."""
        self.run_method('setAnchors', anchors)

    def set_active_comment(self, anchor_id: str | None) -> None:
        self.run_method('setActiveAnchor', anchor_id)

    def scroll_to_comment(self, anchor_id: str) -> None:
        self.run_method('scrollToAnchor', anchor_id)

    def show_diff(self, segments: list[dict[str, Any]], decisions: bool = True) -> None:
        """Replace the document view with a diff (``Segment.as_dict()`` items). decisions=False is view-only."""
        self.run_method('showDiff', segments, decisions)

    def hide_diff(self) -> None:
        self.run_method('hideDiff')

    def set_all_decisions(self, decision: str) -> None:
        """Set every hunk to 'accepted', 'rejected' or 'pending' (hunks with invalid blocks stay unaccepted)."""
        self.run_method('setAllDecisions', decision)

    async def get_decisions(self) -> dict[str, str]:
        return await self.run_method('getDecisions')


ui.context_editor = ContextEditor  # type: ignore[attr-defined]
