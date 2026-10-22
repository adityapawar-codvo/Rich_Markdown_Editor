"""The right-hand panels: comments, version history, and the AI agent. Native NiceGUI elements only."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from nicegui import run, ui

from ..diffing import diff_html, hunks
from ..errors import EditorError, StaleVersion
from ..models import AGENT_USE, COMMENT_RESOLVE, DOC_COMMENT, DOC_EDIT, DOC_PUBLISH, DOC_RESTORE, Comment, Thread
from ..timefmt import format_local
from .layout import FAILED, busy, icon_button

if TYPE_CHECKING:
    from .pages.workspace import Workspace


# ---------------------------------------------------------------------------------------------------- comments

class CommentsPanel:
    def __init__(self, ws: Workspace):
        self.ws = ws
        self.filter = "all"
        self.threads: list[Thread] = []
        self.resolved: dict[str, bool] = {}
        self.pending_anchor: dict | None = None
        self.reply_to: str | None = None
        self.editing: str | None = None
        self.loading = False

    @property
    def can_comment(self) -> bool:
        v = self.ws.view
        return bool(v and DOC_COMMENT in v.capabilities and not self.ws.in_diff)

    def build(self) -> None:
        with ui.column().classes("w-full gap-3"):
            with ui.row().classes("w-full items-center justify-between no-wrap"):
                self.toggle = ui.toggle({"all": "All", "open": "Open", "resolved": "Resolved"}, value="all",
                                        on_change=self._on_filter).props("dense no-caps unelevated toggle-color=primary color=grey-3 text-color=grey-9").mark("comment-filter")
                self.count = ui.label().classes("ws-muted text-caption")
            self.composer = ui.column().classes("w-full gap-2")
            self.list = ui.column().classes("w-full gap-2")
        self.render()

    def _on_filter(self, e) -> None:
        self.filter = e.value
        self.render()

    # -- data

    async def reload(self) -> None:
        v = self.ws.view
        if v is None:
            self.threads = []
            self.render()
            return
        self.loading = True
        self.render()
        threads = await self.ws.call(self.ws.ctx.comments.list_threads, self.ws.actor, v.document.id, "all")
        self.loading = False
        self.threads = [] if threads is FAILED else threads
        self.push_anchors()
        self.render()

    def push_anchors(self) -> None:
        anchors = [
            {"id": t.root.anchor_id, "quote": t.root.quoted_text, "prefix": t.root.anchor_prefix or "",
             "suffix": t.root.anchor_suffix or "", "hint": t.root.anchor_hint or 0, "status": t.root.status}
            for t in self.threads if t.root.anchor_id and not t.root.deleted]
        self.ws.editor.set_comment_anchors(anchors)

    def on_anchors_resolved(self, resolved: dict) -> None:
        self.resolved = resolved or {}
        self.render_list()  # never the composer: that would wipe what the user is typing

    def start_anchored(self, anchor: dict) -> None:
        if not self.can_comment:
            return
        self.pending_anchor = anchor
        self.ws.show_panel("comments")
        self.render()

    def focus_thread(self, thread: Thread) -> None:
        if thread.root.anchor_id:
            self.ws.editor.set_active_comment(thread.root.anchor_id)
            self.ws.editor.scroll_to_comment(thread.root.anchor_id)

    def on_comment_click(self, anchor_id: str) -> None:
        self.ws.editor.set_active_comment(anchor_id)
        self.ws.show_panel("comments")
        ui.run_javascript(f'document.getElementById("c-{anchor_id}")?.scrollIntoView({{block:"center",behavior:"smooth"}})')

    # -- actions

    async def add(self, body: str, *, anchor: dict | None = None, parent_id: str | None = None, button=None) -> bool:
        v = self.ws.view
        async with busy(*([button] if button else [])):
            added = await self.ws.call(self.ws.ctx.comments.add, self.ws.actor, v.document.id, v.version_number,
                                       body, anchor=anchor, parent_id=parent_id)
        if added is FAILED:
            return False
        self.pending_anchor = None
        self.reply_to = None
        await self.reload()
        self.ws.notify("Comment added", type="positive")
        return True

    async def save_edit(self, comment_id: str, body: str, button) -> None:
        async with busy(button):
            done = await self.ws.call(self.ws.ctx.comments.edit, self.ws.actor, comment_id, body)
        if done is not FAILED:
            self.editing = None
            await self.reload()

    async def delete(self, comment: Comment) -> None:
        with ui.dialog() as dialog, ui.card().classes("ws-card"):
            ui.label("Delete this comment?").classes("text-subtitle1")
            ui.label("It is hidden from everyone but stays in the audit trail.").classes("ws-muted text-caption")
            with ui.row().classes("justify-end w-full"):
                ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat no-caps")
                ui.button("Delete", on_click=lambda: dialog.submit(True)).props("unelevated no-caps color=negative")
        if await dialog:
            if await self.ws.call(self.ws.ctx.comments.delete, self.ws.actor, comment.id) is not FAILED:
                await self.reload()

    async def resolve(self, thread: Thread, resolved: bool, button) -> None:
        async with busy(button):
            done = await self.ws.call(self.ws.ctx.comments.set_resolved, self.ws.actor, thread.root.id, resolved)
        if done is not FAILED:
            await self.reload()
            self.ws.notify("Comment resolved" if resolved else "Comment reopened", type="positive")

    # -- rendering

    def visible(self) -> list[Thread]:
        return [t for t in self.threads if self.filter == "all" or t.root.status == self.filter]

    def render(self) -> None:
        self.render_composer()
        self.render_list()

    def render_composer(self) -> None:
        v = self.ws.view
        self.composer.clear()
        with self.composer:
            if v is not None and self.can_comment:
                if self.pending_anchor:
                    self._composer_card(self.pending_anchor)
                else:
                    self._general_composer()

    def render_list(self) -> None:
        open_count = sum(1 for t in self.threads if t.root.status == "open")
        self.count.set_text(f"{open_count} open")
        self.ws.update_comment_badge(open_count)
        self.list.clear()
        with self.list:
            if self.loading:
                for _ in range(3):
                    ui.skeleton("rect", height="72px").classes("w-full")
                return
            threads = self.visible()
            if not threads:
                ui.label("No comments yet. Select text in the document to annotate it, or add a general comment."
                         if self.filter == "all" else f"No {self.filter} comments.").classes("ws-empty")
            for t in threads:
                self._thread_card(t)

    def _general_composer(self) -> None:
        box = ui.textarea(placeholder="Add a general comment").props("autogrow rows=2").mark("general-comment")
        send = icon_button("send", "Post general comment", color="primary").mark("general-send")

        async def submit() -> None:
            text = (box.value or "").strip()
            if not text:
                return
            box.value = ""  # before add(): a successful add rebuilds this composer and deletes the box
            if not await self.add(text, button=send):
                box.value = text

        send.on_click(submit)
        send.classes("self-end")

    def _composer_card(self, anchor: dict) -> None:
        with ui.card().classes("ws-card w-full gap-2 p-3"):
            ui.label("Comment on selected text").classes("ws-section-title")
            ui.label(f"“{anchor['quote'][:240]}”").classes("ws-quote")
            box = ui.textarea(placeholder="Write a comment").props("autogrow rows=2").mark("anchored-comment")
            with ui.row().classes("justify-end w-full gap-1"):
                icon_button("close", "Cancel", self._cancel_pending)
                send = icon_button("send", "Post comment", color="primary").mark("anchored-send")

                async def submit() -> None:
                    if (box.value or "").strip():
                        await self.add(box.value, anchor=anchor, button=send)

                send.on_click(submit)

    def _cancel_pending(self) -> None:
        self.pending_anchor = None
        self.render()

    def _meta_row(self, c: Comment) -> None:
        with ui.row().classes("items-center gap-2 no-wrap w-full"):
            ui.label(c.author_name).classes("text-body2 text-weight-medium")
            ui.label(c.author_role_label).classes("ws-badge role")
            ui.space()
            ui.label(f"v{c.version_number}").classes("ws-badge")
        stamp = format_local(c.created_at, self.ws.tz)
        edited = f" · edited {format_local(c.edited_at, self.ws.tz)}" if c.edited_at else ""
        ui.label(f"{stamp}{edited}").classes("ws-muted text-caption")

    def _thread_card(self, t: Thread) -> None:
        root = t.root
        orphan = bool(root.anchor_id) and self.resolved.get(root.anchor_id) is False
        resolved = root.status == "resolved"
        card = ui.column().classes(f"ws-comment w-full gap-1 {'is-resolved' if resolved else ''}")
        card.props(f'id="c-{root.anchor_id or root.id}"').mark(f"thread-{root.id}")
        card.on("click", lambda t=t: self.focus_thread(t))
        with card:
            self._meta_row(root)
            if root.quoted_text:
                ui.label(f"“{root.quoted_text[:200]}”").classes("ws-quote")
                if orphan:
                    ui.label("text no longer present").classes("ws-badge draft")
            if root.deleted:
                ui.label("This comment was deleted.").classes("ws-muted text-caption")
            elif self.editing == root.id:
                self._edit_box(root)
            else:
                ui.label(root.body).classes("text-body2").style("white-space:pre-wrap")
            if resolved:
                ui.label("Resolved").classes("ws-badge published")
            for reply in t.replies:
                if reply.deleted:
                    continue
                with ui.column().classes("ws-reply gap-1 w-full"):
                    self._meta_row(reply)
                    if self.editing == reply.id:
                        self._edit_box(reply)
                    else:
                        ui.label(reply.body).classes("text-body2").style("white-space:pre-wrap")
                    self._actions(reply, t, reply=True)
            if self.reply_to == root.id:
                self._reply_box(root)
            self._actions(root, t)

    def _actions(self, c: Comment, t: Thread, reply: bool = False) -> None:
        v = self.ws.view
        mine = c.author_id == self.ws.actor.user_id
        with ui.row().classes("gap-0 items-center").on("click.stop"):
            if not reply and not c.deleted and DOC_COMMENT in v.capabilities:
                icon_button("reply", "Reply", lambda c=c: self._open_reply(c), size="sm").mark(f"reply-{c.id}")
            if mine and not c.deleted and DOC_COMMENT in v.capabilities:
                icon_button("edit", "Edit comment", lambda c=c: self._open_edit(c), size="sm")
                icon_button("delete", "Delete comment", lambda c=c: self.delete(c), size="sm")
            if not reply and COMMENT_RESOLVE in v.capabilities:
                if c.status == "open":
                    b = icon_button("check_circle", "Resolve", size="sm").mark(f"resolve-{c.id}")
                    b.on_click(lambda t=t, b=b: self.resolve(t, True, b))
                else:
                    b = icon_button("replay", "Reopen", size="sm").mark(f"reopen-{c.id}")
                    b.on_click(lambda t=t, b=b: self.resolve(t, False, b))

    def _open_reply(self, c: Comment) -> None:
        self.reply_to, self.editing = c.id, None
        self.render()

    def _open_edit(self, c: Comment) -> None:
        self.editing, self.reply_to = c.id, None
        self.render()

    def _reply_box(self, root: Comment) -> None:
        with ui.column().classes("w-full gap-1").on("click.stop"):
            box = ui.textarea(placeholder="Reply").props("autogrow rows=1").mark(f"reply-box-{root.id}")
            with ui.row().classes("justify-end w-full gap-1"):
                icon_button("close", "Cancel reply", self._close_inline, size="sm")
                send = icon_button("send", "Post reply", color="primary", size="sm").mark(f"reply-send-{root.id}")

                async def submit() -> None:
                    if (box.value or "").strip():
                        await self.add(box.value, parent_id=root.id, button=send)

                send.on_click(submit)

    def _edit_box(self, c: Comment) -> None:
        with ui.column().classes("w-full gap-1").on("click.stop"):
            box = ui.textarea(value=c.body).props("autogrow rows=2")
            with ui.row().classes("justify-end w-full gap-1"):
                icon_button("close", "Cancel edit", self._close_inline, size="sm")
                send = icon_button("check", "Save comment", color="primary", size="sm")
                send.on_click(lambda: self.save_edit(c.id, box.value, send))

    def _close_inline(self) -> None:
        self.reply_to = self.editing = None
        self.render()


# ---------------------------------------------------------------------------------------------------- history

class HistoryPanel:
    def __init__(self, ws: Workspace):
        self.ws = ws

    def build(self) -> None:
        self.box = ui.column().classes("w-full gap-2")
        self.render([])

    async def reload(self) -> None:
        v = self.ws.view
        versions = await self.ws.call(self.ws.ctx.docs.list_versions, self.ws.actor, v.document.id) if v else []
        self.render([] if versions is FAILED else versions)

    def render(self, versions) -> None:
        v = self.ws.view
        self.box.clear()
        with self.box:
            if not versions:
                ui.label("No versions yet.").classes("ws-empty")
                return
            latest = v.document.current_version if v else 0
            for info in versions:
                shown = v is not None and info.version_number == v.version_number
                with ui.column().classes(f"ws-comment w-full gap-1 {'is-active' if shown else ''}").mark(f"version-{info.version_number}"):
                    with ui.row().classes("items-center gap-2 no-wrap w-full"):
                        ui.label(f"Version {info.version_number}").classes("text-body2 text-weight-medium")
                        if info.published:
                            ui.label("Published").classes("ws-badge published")
                        else:
                            ui.label("Draft").classes("ws-badge draft")
                        if info.source != "manual":
                            ui.label(info.source).classes("ws-badge")
                        ui.space()
                        if shown:
                            ui.label("Viewing").classes("ws-muted text-caption")
                    detail = f"{info.created_by} · {format_local(info.created_at, self.ws.tz)}"
                    if info.restored_from_version:
                        detail += f" · restored from v{info.restored_from_version}"
                    ui.label(detail).classes("ws-muted text-caption")
                    if info.change_note:
                        ui.label(f"“{info.change_note}”").classes("text-body2")
                    with ui.row().classes("gap-0"):
                        icon_button("visibility", "View this version", lambda n=info.version_number: self.ws.view_version(n), size="sm")
                        if info.version_number != latest:
                            icon_button("compare_arrows", "Compare with latest",
                                        lambda n=info.version_number: self.ws.compare(n), size="sm").mark(f"compare-{info.version_number}")
                            if v and DOC_RESTORE in v.capabilities:
                                icon_button("restore", "Restore as new draft",
                                            lambda n=info.version_number: self.ws.restore(n), size="sm").mark(f"restore-{info.version_number}")


# ---------------------------------------------------------------------------------------------------- agent

class AgentPanel:
    def __init__(self, ws: Workspace):
        self.ws = ws
        self.messages: dict[str, list[tuple[str, str]]] = {}
        self.selected: set[str] = set()
        self.proposal = None
        self.running = False
        self.cancel: asyncio.Event | None = None
        self.decisions: dict[str, str] = {}
        self.invalid: set[str] = set()

    @property
    def doc_id(self) -> str | None:
        return self.ws.view.document.id if self.ws.view else None

    def build(self) -> None:
        self.column = ui.column().classes("w-full gap-3")
        self.render()

    def reset(self) -> None:
        self.proposal = None
        self.decisions, self.invalid = {}, set()
        self.render()

    def render(self) -> None:
        ws, v = self.ws, self.ws.view
        self.column.clear()
        with self.column:
            if v is None or AGENT_USE not in v.capabilities or DOC_EDIT not in v.capabilities:
                ui.label("The editing assistant is available to the product owner.").classes("ws-empty")
                return
            if not ws.ctx.agent.enabled:
                ui.label("The assistant is off. Set OPENROUTER_API_KEY (and optionally OPENROUTER_MODEL) in the "
                         "environment and restart.").classes("ws-banner info")
                return
            if not v.editable:
                ui.label("Open the latest draft to use the assistant.").classes("ws-empty")
                return
            history = self.messages.setdefault(v.document.id, [])
            with ui.column().classes("w-full gap-2").mark("agent-chat"):
                if not history:
                    ui.label("Describe a change in plain language, for example “Add a risks table for vendor "
                             "lock-in” or “Rewrite the goals more concisely”. You review every change before "
                             "it is saved.").classes("ws-empty")
                for who, text in history:
                    ui.label(text).classes("ws-bubble-user" if who == "user" else "ws-bubble-agent").style("white-space:pre-wrap")
            open_threads = [t for t in ws.comments.threads if t.root.status == "open" and not t.root.deleted]
            if open_threads and self.proposal is None:
                ui.label("Include open comments").classes("ws-section-title")
                with ui.column().classes("w-full gap-0"):
                    for t in open_threads:
                        ui.checkbox(f"{t.root.author_name}: {t.root.body[:70]}", value=t.root.id in self.selected,
                                    on_change=lambda e, i=t.root.id: self._toggle(i, e.value)).props("dense").classes("text-caption")
            if self.proposal is not None:
                self._review_controls()
            else:
                box = ui.textarea(placeholder="Ask the assistant to edit this document").props("autogrow rows=2").mark("agent-prompt")
                with ui.row().classes("w-full justify-end gap-1"):
                    if self.running:
                        icon_button("stop_circle", "Cancel request", self._cancel)
                    send = icon_button("send", "Send to the assistant", color="primary").mark("agent-send")
                    send.on_click(lambda: self.propose(box, send))
                    if self.running:
                        send.disable()

    def _toggle(self, comment_id: str, on: bool) -> None:
        (self.selected.add if on else self.selected.discard)(comment_id)

    def _cancel(self) -> None:
        if self.cancel:
            self.cancel.set()

    async def propose(self, box: ui.textarea, send: ui.button) -> None:
        ws = self.ws
        prompt = (box.value or "").strip()
        if not prompt or self.running:
            return
        if ws.editor.dirty:
            self.ws.notify("Save your changes first so the assistant works on the saved draft.", type="warning")
            return
        self.messages.setdefault(self.doc_id, []).append(("user", prompt))
        self.running, self.cancel = True, asyncio.Event()
        self.render()
        ws.set_status("The assistant is working…")
        try:
            proposal = await ws.ctx.agent.propose(ws.actor, self.doc_id, prompt, sorted(self.selected), self.cancel)
        except EditorError as exc:
            self.messages[self.doc_id].append(("agent", exc.message))
            self.ws.notify(exc.message, type="negative")
            proposal = None
        except Exception:
            self.messages[self.doc_id].append(("agent", "Something went wrong. Your document was not changed."))
            self.ws.notify("Something went wrong. Your document was not changed.", type="negative")
            proposal = None
        finally:
            self.running = False
            ws.set_status(None)
        if proposal is None:
            self.render()
            return
        n = len(hunks(proposal.segments))
        if n == 0:
            self.messages[self.doc_id].append(("agent", "I found nothing to change for that request."))
            self.render()
            return
        self.proposal = proposal
        self.decisions = {}
        self.messages[self.doc_id].append(("agent", f"I propose {n} change{'s' if n != 1 else ''}. Review them in the document."))
        self.render()
        await ws.show_agent_diff([s.as_dict() for s in proposal.segments])

    def on_hunk_decision(self, payload: dict) -> None:
        self.decisions[payload["id"]] = payload["decision"]

    def on_diff_ready(self, info: dict) -> None:
        self.invalid = set(info.get("invalid") or [])
        if self.invalid:
            self.ws.notify(f"{len(self.invalid)} change(s) contain an invalid diagram or chart and cannot be accepted.", type="warning")

    def _review_controls(self) -> None:
        total = len(hunks(self.proposal.segments))
        ui.label(f"Review {total} proposed change{'s' if total != 1 else ''}").classes("ws-section-title")
        ui.label("Use the check and cross on each change, or apply them all at once. Unreviewed changes are not applied "
                 "when you choose “Apply accepted”.").classes("ws-muted text-caption")
        with ui.row().classes("gap-1"):
            icon_button("done_all", "Accept all changes", lambda: self._set_all("accepted"), color="positive").mark("agent-accept-all")
            icon_button("remove_done", "Reject all changes", lambda: self._set_all("rejected")).mark("agent-reject-all")
            apply = icon_button("save", "Apply accepted changes as a new draft", color="primary").mark("agent-apply")
            apply.on_click(lambda: self.apply(apply))
            icon_button("close", "Discard proposal", self.discard).mark("agent-discard")

    def _set_all(self, value: str) -> None:
        self.ws.editor.set_all_decisions(value)
        hunk_ids = [h.hunk_id for h in hunks(self.proposal.segments)]
        for h in hunk_ids:
            if value == "accepted" and h in self.invalid:
                continue
            self.decisions[h] = value

    async def apply(self, button) -> None:
        ws = self.ws
        accepted = {h for h, d in self.decisions.items() if d == "accepted" and h not in self.invalid}
        async with busy(button):
            try:
                if not accepted:
                    await asyncio.to_thread(ws.ctx.agent.reject, ws.actor, self.proposal.request_id)
                    self.messages[self.doc_id].append(("agent", "No changes were applied."))
                    view = None
                else:
                    view = await asyncio.to_thread(ws.ctx.agent.resolve, ws.actor, self.proposal.request_id, accepted)
                    self.messages[self.doc_id].append(("agent", f"Saved as version {view.version_number} (draft)."))
            except StaleVersion:
                self.ws.notify("The document changed while you were reviewing. Reload and ask again.", type="negative")
                self.messages[self.doc_id].append(("agent", "The document changed, so I did not apply these changes."))
                view = None
            except EditorError as exc:
                self.ws.notify(exc.message, type="negative")
                return
        self.proposal, self.decisions, self.invalid = None, {}, set()
        await ws.leave_diff(reload_latest=True)
        self.render()
        if view is not None:
            self.ws.notify(f"Saved as version {view.version_number}", type="positive")

    async def discard(self) -> None:
        if self.proposal is not None:
            await asyncio.to_thread(self.ws.ctx.agent.reject, self.ws.actor, self.proposal.request_id)
        self.proposal, self.decisions, self.invalid = None, {}, set()
        await self.ws.leave_diff(reload_latest=False)
        self.render()
