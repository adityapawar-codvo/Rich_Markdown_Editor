"""The workspace: documents on the left, the editor in the centre, comments / history / assistant on the right.

Persona switching stands in for sign-in (this project is standalone; the real platform supplies the identity).
Every action is authorized by the services, not by what this page shows."""
from __future__ import annotations

from dataclasses import dataclass

from nicegui import app, run, ui

from ...diffing import diff_html, hunks
from ...errors import AlreadyPublished, EditorError, StaleVersion
from ...models import (
    AGENT_USE,
    DOC_COMMENT,
    DOC_CREATE,
    DOC_EDIT,
    DOC_EXPORT,
    DOC_EXPORT_DRAFT,
    DOC_PUBLISH,
    DOC_READ_DRAFT,
    Actor,
    DocumentView,
    Project,
)
from ...importer import ACCEPT, MAX_BYTES, convert_safe, name_error
from ...timefmt import format_local
from ..context import AppContext
from ..editor import ContextEditor
from ..layout import FAILED, busy, icon_button, page_colors
from ..panels import AgentPanel, CommentsPanel, HistoryPanel

DOC_TYPES = ["PRD", "Architecture", "Specification", "Test plan", "Notes", "Imported"]


@dataclass
class Stash:
    """Unsaved edits set aside while the owner looks at another version of the same document."""
    doc_id: str
    base_version: int  # the saved version those edits were made on
    html: str


def personas(ctx: AppContext) -> dict[str, str]:
    """user id -> label, for the demo's persona switcher."""
    with ctx.db.read() as conn:
        rows = conn.execute(
            """select u.id, u.display_name, t.name as tenant,
                      (select group_concat(distinct r.name) from memberships m
                         join membership_roles mr on mr.membership_id = m.id
                         join roles r on r.id = mr.role_id where m.user_id = u.id) as roles
               from users u join tenants t on t.id = u.tenant_id order by t.name, u.rowid""").fetchall()
    return {r["id"]: f"{r['display_name']} · {r['roles'] or 'No role'} · {r['tenant']}" for r in rows}


class Workspace:
    def __init__(self, ctx: AppContext, actor: Actor, tz: str | None):
        self.ctx, self.actor, self.tz = ctx, actor, tz
        self.client = ui.context.client
        self.project: Project | None = None
        self.projects: list[Project] = []
        self.docs = []
        self.view: DocumentView | None = None
        self.in_diff = False
        self.diff_kind: str | None = None  # "compare" | "agent"
        self.mode = "latest"  # latest | version | published
        self.stale = False
        self.stash: Stash | None = None
        self.base_override: int | None = None  # save against this version when restored edits are out of date
        self.comments = CommentsPanel(self)
        self.history = HistoryPanel(self)
        self.agent = AgentPanel(self)

    # ------------------------------------------------------------------ helpers

    async def call(self, fn, *args, **kwargs):
        """Run a blocking service call off the event loop. Errors are reported to the user; FAILED is returned."""
        try:
            return await run.io_bound(fn, *args, **kwargs)
        except StaleVersion as exc:
            self.stale = True
            self.render_banners()
            self.notify(exc.message, type="warning")
        except EditorError as exc:
            self.notify(exc.message, type="negative")
        except Exception:
            self.notify("Something went wrong. Please try again.", type="negative")
        return FAILED

    def notify(self, *args, **kwargs) -> None:
        """A toast from any handler. Panels rebuild their widgets, and a handler may outlive the button that started
        it, so the toast is created in the page's own (always alive) content slot."""
        with self.client.content:
            ui.notify(*args, **kwargs)

    def show_panel(self, name: str) -> None:
        self.right.value = True
        self.tabs.value = name

    def set_status(self, text: str | None) -> None:
        self.status.set_text(text or "")
        self.status_spinner.set_visibility(bool(text))

    def update_comment_badge(self, open_count: int) -> None:
        if getattr(self, "comment_badge", None) is None:  # panels render once before the toolbar exists
            return
        self.comment_badge.set_text(str(open_count))
        self.comment_badge.set_visibility(open_count > 0)

    # ------------------------------------------------------------------ build

    def build(self) -> None:
        caps_icon = ui.dark_mode(value=app.storage.user.get("dark", False))
        self.dark = caps_icon
        with ui.header().classes("ws-header items-center gap-3 px-4 no-wrap").props("height-hint=56"):
            icon_button("menu", "Toggle documents", lambda: self.left.toggle())
            ui.label("Context Editor").classes("ws-brand")
            self.project_label = ui.label().classes("ws-muted text-body2")
            ui.space()
            self.persona = ui.select(personas(self.ctx), value=self.actor.user_id, on_change=self._switch_persona) \
                .props("dense borderless options-dense").classes("w-80 max-w-[40vw]").mark("persona")
            icon_button("dark_mode", "Toggle dark mode", self._toggle_dark).mark("dark-toggle")

        self.left = ui.left_drawer(value=None).props("bordered width=290 breakpoint=1000").classes("ws-drawer p-3")
        with self.left:
            with ui.row().classes("w-full items-center justify-between no-wrap"):
                ui.label("Documents").classes("ws-section-title")
                with ui.row().classes("gap-0 no-wrap"):
                    self.upload_button = icon_button("upload_file", "Upload a file", self.upload_dialog).mark("upload-doc")
                    self.new_button = icon_button("add", "New document", self.new_document_dialog).mark("new-doc")
            self.project_select = ui.select({}, on_change=self._project_changed).props("dense").classes("w-full").mark("project")
            self.doc_list = ui.column().classes("w-full gap-1 mt-2")

        self.right = ui.right_drawer(value=None).props("bordered width=400 breakpoint=1350").classes("ws-drawer p-3")
        with self.right:
            with ui.tabs().props("dense no-caps align=left").classes("w-full") as self.tabs:
                self.tab_comments = ui.tab("comments", label="Comments").mark("tab-comments")
                self.tab_history = ui.tab("history", label="History").mark("tab-history")
                self.tab_agent = ui.tab("agent", label="Assistant").mark("tab-agent")
            with ui.tab_panels(self.tabs, value="comments").props("animated=false").classes("w-full bg-transparent"):
                with ui.tab_panel("comments").classes("p-0 pt-3"):
                    self.comments.build()
                with ui.tab_panel("history").classes("p-0 pt-3"):
                    self.history.build()
                with ui.tab_panel("agent").classes("p-0 pt-3"):
                    self.agent.build()

        with ui.column().classes("w-full max-w-[1100px] mx-auto gap-3 p-4"):
            self.meta_card = ui.column().classes("ws-card w-full p-4 gap-3")
            self.banners = ui.column().classes("w-full gap-2")
            with ui.row().classes("w-full items-center gap-1 no-wrap"):
                self.save_btn = icon_button("save", "Save as new version (Ctrl/Cmd+S)", self.save, color="primary").mark("save")
                self.publish_btn = icon_button("publish", "Publish this version", self.publish_dialog).mark("publish")
                self.rename_btn = icon_button("drive_file_rename_outline", "Rename document", self.rename_dialog).mark("rename")
                self.export_btn = icon_button("download", "Export").mark("export")
                with self.export_btn:
                    with ui.menu() as menu:
                        ui.menu_item("PDF (.pdf)", on_click=lambda: self.export("pdf")).mark("export-pdf")
                        ui.menu_item("Word (.docx)", on_click=lambda: self.export("docx")).mark("export-docx")
                self.published_btn = icon_button("visibility", "View what the team sees", self.toggle_published).mark("published-view")
                self.dirty_dot = ui.element("span").classes("ws-dirty").props('role="status" aria-label="Unsaved changes"')
                self.dirty_dot.set_visibility(False)
                self.dirty_label = ui.label("Unsaved changes").classes("ws-muted text-caption")
                self.dirty_label.set_visibility(False)
                self.status_spinner = ui.spinner(size="sm")
                self.status_spinner.set_visibility(False)
                self.status = ui.label().classes("ws-muted text-caption")
                ui.space()
                self.panel_btn = icon_button("forum", "Show or hide the side panel", lambda: self.right.toggle()).mark("toggle-panel")
                with self.panel_btn:
                    self.comment_badge = ui.badge("0", color="primary").props("floating rounded")
                    self.comment_badge.set_visibility(False)
            with ui.element("div").classes("ws-editor-shell w-full").mark("editor-shell"):
                self.editor = ContextEditor(
                    value="", readonly=True,
                    on_save=self.save, on_dirty=lambda e: self.refresh_controls(),
                    on_selection_comment=lambda e: self.comments.start_anchored(e.args),
                    on_comment_click=lambda e: self.comments.on_comment_click(e.args),
                    on_anchors_resolved=lambda e: self.comments.on_anchors_resolved(e.args),
                    on_hunk_decision=lambda e: self.agent.on_hunk_decision(e.args),
                    on_diff_ready=lambda e: self.agent.on_diff_ready(e.args),
                ).mark("editor")
        self.render_empty()

    def _toggle_dark(self) -> None:
        self.dark.toggle()
        app.storage.user["dark"] = bool(self.dark.value)

    def _switch_persona(self, e) -> None:
        app.storage.user["user_id"] = e.value
        ui.navigate.reload()

    # ------------------------------------------------------------------ data loading

    async def init(self) -> None:
        self.projects = await run.io_bound(self.ctx.authz.list_projects, self.actor)
        self.project_select.set_options({p.id: f"{p.name} ({p.project_key})" for p in self.projects},
                                        value=self.projects[0].id if self.projects else None)
        if not self.projects:
            self.render_empty("You are not assigned to any project yet.")
            return
        await self._project_changed(None)

    async def _project_changed(self, _e) -> None:
        pid = self.project_select.value
        self.project = next((p for p in self.projects if p.id == pid), None)
        if self.project is None:
            return
        self.project_label.set_text(self.project.name)
        await self.reload_docs()
        if self.docs:
            await self.open_document(self.docs[0].id)
        else:
            self.view = None
            self.render_empty("No documents yet." + (" Create the first one with the + button." if self.can_create else ""))

    @property
    def can_create(self) -> bool:
        return self._project_caps is not None and DOC_CREATE in self._project_caps

    _project_caps: frozenset | None = None

    async def reload_docs(self) -> None:
        caps = await self.call(self.ctx.docs.capabilities, self.actor, self.project.id)
        self._project_caps = None if caps is FAILED else caps
        docs = await self.call(self.ctx.docs.list_documents, self.actor, self.project.id)
        self.docs = [] if docs is FAILED else docs
        self.new_button.set_visibility(self.can_create)
        self.upload_button.set_visibility(self.can_create)
        self.render_docs()

    def render_docs(self) -> None:
        self.doc_list.clear()
        with self.doc_list:
            if not self.docs:
                ui.label("Nothing here yet.").classes("ws-empty")
            for d in self.docs:
                active = self.view is not None and d.id == self.view.document.id
                with ui.row().classes(f"ws-doc-item w-full items-center no-wrap {'is-active' if active else ''}") \
                        .on("click", lambda d=d: self.open_document(d.id)).mark(f"doc-{d.id}"):
                    with ui.column().classes("gap-0 min-w-0").style("flex:1 1 0"):
                        ui.label(d.title).classes("ws-doc-title ellipsis w-full")
                        ui.label(f"{d.doc_type} · {format_local(d.updated_at, self.tz)}").classes("ws-muted text-caption ellipsis w-full")
                    ui.label(d.status).classes(f"ws-badge {d.status.lower()}").style("flex:0 0 auto")

    # ------------------------------------------------------------------ opening documents

    async def open_document(self, doc_id: str, version: int | None = None, mode: str = "latest") -> None:
        same_doc = self.view is not None and self.view.document.id == doc_id
        going_latest = mode == "latest"
        pending = bool(self.editor.dirty or self.stash)
        if self.view is not None and pending and not same_doc:
            if not await self.confirm("Discard unsaved changes?", "Your edits in this document have not been saved.", "Discard"):
                return
            self.stash = self.base_override = None
        elif same_doc and going_latest and self.view.editable and self.editor.dirty:
            return  # already on the latest draft with edits in progress: opening it again must not reload over them
        elif same_doc and not going_latest and self.view.editable and self.editor.dirty and self.stash is None:
            # Looking at another version (what the team sees, an older one): set the edits aside, bring them back later.
            self.stash = Stash(doc_id, self.base_override or self.view.version_number, await self.editor.get_html())
        view = await self.call(self.ctx.docs.get, self.actor, doc_id, version)
        if view is FAILED:
            return
        if self.in_diff:
            self.editor.hide_diff()
            self.in_diff, self.diff_kind = False, None
        self.view, self.mode, self.stale = view, mode, False
        self.editor.readonly = not view.editable
        self.editor.commenting = DOC_COMMENT in view.capabilities
        self.editor.set_value(view.html)
        self.editor.run_method("setContent", view.html)
        if going_latest and self.stash is not None and self.stash.doc_id == doc_id:
            self._restore_stash(view)
        elif going_latest:
            self.stash = self.base_override = None
        if not same_doc:
            self.agent.reset()
        self.render_meta()
        self.render_banners()
        self.render_docs()
        self.refresh_controls()
        await self.comments.reload()
        await self.history.reload()
        self.agent.render()

    def _restore_stash(self, view: DocumentView) -> None:
        """Put the set-aside edits back into the editor. If the document moved on while the owner was away, the
        edits stay visible but are saved against the version they were made on, so the server rejects the save
        with the usual "document changed" message instead of silently overwriting someone else's work."""
        stash, self.stash = self.stash, None
        self.editor.run_method("restoreEdits", stash.html)
        if stash.base_version != view.version_number:
            self.base_override, self.stale = stash.base_version, True
            self.notify("The document changed while you were away. Your edits are still here, but saving will be "
                        "refused until you reload or copy them.", type="warning")
        else:
            self.base_override = None

    async def reload_latest(self) -> None:
        if self.view is not None:
            self.editor.dirty = False
            self.stash = self.base_override = None
            await self.open_document(self.view.document.id)
            await self.reload_docs()

    def render_empty(self, text: str = "Select a document to begin.") -> None:
        self.meta_card.clear()
        with self.meta_card:
            ui.label(text).classes("ws-empty w-full")
        self.banners.clear()
        self.refresh_controls()

    def render_meta(self) -> None:
        v = self.view
        m = v.metadata
        self.meta_card.clear()
        with self.meta_card:
            with ui.row().classes("w-full items-center justify-between no-wrap"):
                ui.label(m.title).classes("ws-title").mark("doc-title")
                with ui.row().classes("items-center gap-2 no-wrap"):
                    ui.label(m.status).classes(f"ws-badge {m.status.lower()}").mark("doc-status")
                    ui.label(f"v{m.version_number}").classes("ws-badge").mark("doc-version")
            local = lambda iso: format_local(iso, self.tz)  # noqa: E731
            published = f"{local(m.last_published_at)} · {m.last_published_by}" if m.last_published_at else "Not published yet"
            with ui.element("dl").classes("ws-meta w-full m-0"):
                for label, value in (
                    ("Type", m.doc_type), ("Version", f"v{m.version_number}"), ("Status", m.status),
                    ("Created", f"{local(m.created_at)} · {m.created_by}"),
                    ("Last edited", f"{local(m.last_edited_at)} · {m.last_edited_by}"),
                    ("Last published", published)):
                    with ui.element("div"):
                        ui.element("dt").props(f'innerHTML="{label}"')
                        ui.element("dd").props(f'innerHTML="{_esc(value)}"')

    def render_banners(self) -> None:
        v = self.view
        self.banners.clear()
        if v is None:
            return
        with self.banners:
            if self.stash is not None and not self.in_diff:
                ui.label("Your unsaved edits are kept. Go back to the latest version to continue editing.") \
                    .classes("ws-banner info w-full").mark("kept-banner")
            if self.stale:
                with ui.row().classes("ws-banner error w-full items-center no-wrap gap-2").mark("stale-banner"):
                    ui.label("This document changed since you opened it. Reload to continue; your text stays in the "
                             "editor until you do.").classes("grow")
                    icon_button("content_copy", "Copy my text", self._copy_mine)
                    icon_button("refresh", "Reload latest version", self.reload_latest).mark("stale-reload")
            if self.in_diff and self.diff_kind == "compare":
                with ui.row().classes("ws-banner info w-full items-center no-wrap gap-2"):
                    ui.label(self._compare_note).classes("grow")
                    icon_button("close", "Close comparison", lambda: self.leave_diff(reload_latest=False))
            elif self.in_diff and self.diff_kind == "agent":
                ui.label("Reviewing the assistant’s proposal. Nothing is saved until you apply the changes you accept.") \
                    .classes("ws-banner info w-full")
            latest = v.document.current_version if DOC_READ_DRAFT in v.capabilities else v.document.published_version
            if self.in_diff:
                return
            if self.mode == "published":
                with ui.row().classes("ws-banner info w-full items-center no-wrap gap-2"):
                    ui.label("This is the version your team sees.").classes("grow")
                    icon_button("arrow_back", "Back to the latest version", lambda: self.open_document(v.document.id))
            elif v.version_number != latest:
                with ui.row().classes("ws-banner warn w-full items-center no-wrap gap-2").mark("old-version-banner"):
                    ui.label(f"Viewing version {v.version_number} (read-only).").classes("grow")
                    icon_button("arrow_back", "Back to the latest version", lambda: self.open_document(v.document.id))

    _compare_note = ""

    async def _copy_mine(self) -> None:
        ui.clipboard.write(await self.editor.get_html())
        self.notify("Copied your version to the clipboard", type="positive")

    def refresh_controls(self) -> None:
        v = self.view
        dirty = bool(v and self.editor.dirty)
        kept = bool(v and self.stash is not None)
        self.dirty_dot.set_visibility(dirty or kept)
        self.dirty_label.set_text("Unsaved changes (kept)" if kept and not dirty else "Unsaved changes")
        self.dirty_label.set_visibility(dirty or kept)
        self.editor.guard = kept  # warn before the page is closed while edits are only held aside
        can_edit = bool(v and v.editable and not self.in_diff)
        self.save_btn.set_enabled(can_edit and dirty)
        self.rename_btn.set_visibility(bool(v and DOC_EDIT in v.capabilities))
        self.rename_btn.set_enabled(can_edit and not dirty)
        can_publish = bool(v and DOC_PUBLISH in v.capabilities and v.editable and v.is_draft_view and not dirty and not self.in_diff)
        self.publish_btn.set_visibility(bool(v and DOC_PUBLISH in v.capabilities))
        self.publish_btn.set_enabled(can_publish)
        can_export = bool(v and (DOC_EXPORT_DRAFT if v.is_draft_view else DOC_EXPORT) in v.capabilities and not self.in_diff)
        self.export_btn.set_enabled(can_export)
        self.published_btn.set_visibility(bool(v and DOC_READ_DRAFT in v.capabilities and v.document.published_version))

    # ------------------------------------------------------------------ actions

    async def confirm(self, title: str, body: str, action: str) -> bool:
        with ui.dialog() as dialog, ui.card().classes("ws-card").style("min-width:340px"):
            ui.label(title).classes("text-subtitle1 text-weight-medium")
            ui.label(body).classes("ws-muted text-body2")
            with ui.row().classes("justify-end w-full"):
                ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat no-caps")
                ui.button(action, on_click=lambda: dialog.submit(True)).props("unelevated no-caps color=primary").mark("confirm")
        return bool(await dialog)

    async def save(self) -> None:
        v = self.view
        # No dirty check here: the dirty flag trails typing by a moment, and an unchanged save is a no-op.
        if v is None or not v.editable or self.in_diff:
            return
        async with busy(self.save_btn):
            html = await self.editor.get_html()
            expected = self.base_override or v.version_number
            saved = await self.call(self.ctx.docs.save_draft, self.actor, v.document.id, expected, html)
        if saved is FAILED:
            return
        self.base_override = None
        self.view = saved
        self.editor.mark_clean()
        self.editor.dirty = False
        self.render_meta()
        self.refresh_controls()
        self.render_banners()
        await self.reload_docs()
        await self.history.reload()
        self.notify("No changes to save" if saved.unchanged else f"Saved as version {saved.version_number} (draft)",
                  type="info" if saved.unchanged else "positive")

    async def publish_dialog(self) -> None:
        v = self.view
        if v is None:
            return
        with ui.dialog() as dialog, ui.card().classes("ws-card").style("min-width:420px"):
            ui.label(f"Publish version {v.version_number}?").classes("text-subtitle1 text-weight-medium")
            ui.label("Your team will see this version and will no longer see earlier ones. You can keep working on new "
                     "drafts without affecting what they see.").classes("ws-muted text-body2")
            note = ui.textarea("Change note (optional)").props("autogrow rows=2 maxlength=1000").mark("publish-note")
            with ui.row().classes("justify-end w-full"):
                ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat no-caps")
                ui.button("Publish", on_click=lambda: dialog.submit(note.value or "")).props("unelevated no-caps color=primary").mark("publish-confirm")
        result = await dialog
        if result is None:
            return
        async with busy(self.publish_btn):
            try:
                view = await run.io_bound(self.ctx.docs.publish, self.actor, v.document.id, v.version_number, result)
            except AlreadyPublished as exc:
                self.notify(exc.message, type="warning")
                return
            except StaleVersion as exc:
                self.stale = True
                self.render_banners()
                self.notify(exc.message, type="warning")
                return
            except EditorError as exc:
                self.notify(exc.message, type="negative")
                return
        self.view = view
        self.render_meta()
        self.refresh_controls()
        self.render_banners()
        await self.reload_docs()
        await self.history.reload()
        self.notify(f"Version {view.version_number} published", type="positive")

    async def rename_dialog(self) -> None:
        v = self.view
        with ui.dialog() as dialog, ui.card().classes("ws-card").style("min-width:380px"):
            ui.label("Rename document").classes("text-subtitle1 text-weight-medium")
            ui.label("Renaming saves a new version.").classes("ws-muted text-caption")
            title = ui.input("Title", value=v.metadata.title).props("maxlength=200").mark("rename-input")
            with ui.row().classes("justify-end w-full"):
                ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat no-caps")
                ui.button("Rename", on_click=lambda: dialog.submit(title.value)).props("unelevated no-caps color=primary").mark("rename-confirm")
        new_title = await dialog
        if not new_title or new_title.strip() == v.metadata.title:
            return
        saved = await self.call(self.ctx.docs.save_draft, self.actor, v.document.id, v.version_number, v.html, title=new_title)
        if saved is FAILED:
            return
        self.view = saved
        self.render_meta()
        await self.reload_docs()
        await self.history.reload()
        self.notify("Document renamed", type="positive")

    async def new_document_dialog(self) -> None:
        with ui.dialog() as dialog, ui.card().classes("ws-card").style("min-width:400px"):
            ui.label("New document").classes("text-subtitle1 text-weight-medium")
            title = ui.input("Title").props("maxlength=200").mark("new-title")
            kind = ui.select(DOC_TYPES, value=DOC_TYPES[0], label="Type", new_value_mode="add-unique", with_input=True).mark("new-type")
            with ui.row().classes("justify-end w-full"):
                ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat no-caps")
                ui.button("Create", on_click=lambda: dialog.submit((title.value, kind.value))).props("unelevated no-caps color=primary").mark("new-create")
        result = await dialog
        if not result:
            return
        created = await self.call(self.ctx.docs.create_document, self.actor, self.project.id, result[0], result[1])
        if created is FAILED:
            return
        await self.reload_docs()
        await self.open_document(created.document.id)
        self.notify("Document created (draft)", type="positive")

    async def upload_dialog(self) -> None:
        """Upload an existing file: it is converted on the server and opens as a new, fully editable draft."""
        allowed = await self.call(self.ctx.docs.can_create, self.actor, self.project.id)
        if allowed is FAILED or not allowed:
            if allowed is not FAILED:
                self.notify("You do not have permission to add documents.", type="negative")
            return
        found: dict = {"imported": None}
        with ui.dialog() as dialog, ui.card().classes("ws-card").style("min-width:480px;max-width:560px"):
            ui.label("Upload a file").classes("text-subtitle1 text-weight-medium")
            ui.label("Word, PowerPoint, Excel, PDF, Markdown, HTML, CSV or text. It opens in the editor and stays fully "
                     "editable. Images are not imported.").classes("ws-muted text-body2")
            upload = ui.upload(auto_upload=True, max_files=1, max_file_size=MAX_BYTES,
                               label="Choose a file or drop it here").props(f'accept="{ACCEPT}" flat bordered') \
                .classes("w-full").mark("upload-input")
            with ui.row().classes("items-center gap-2 no-wrap"):
                spinner = ui.spinner(size="sm")
                spinner.set_visibility(False)
                status = ui.label().classes("text-body2").props('role="status"')
            with ui.column().classes("w-full gap-2") as form:
                title = ui.input("Title").props("maxlength=200").mark("upload-title")
                kind = ui.select(DOC_TYPES, value="Imported", label="Type", new_value_mode="add-unique",
                                 with_input=True).mark("upload-type")
                summary = ui.label().classes("ws-muted text-caption")
                notes_box = ui.column().classes("gap-1 w-full")
            form.set_visibility(False)
            with ui.row().classes("justify-end w-full"):
                ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat no-caps")
                create = ui.button("Open in editor", on_click=lambda: dialog.submit(
                    (found["imported"], title.value, kind.value))).props("unelevated no-caps color=primary").mark("upload-create")
                create.disable()

        async def handle(e) -> None:
            spinner.set_visibility(True)
            status.set_text(f"Reading {e.file.name}…")
            status.classes(remove="text-negative")
            create.disable()
            form.set_visibility(False)
            try:
                data = await e.file.read()
                imported, error = await run.cpu_bound(convert_safe, e.file.name, data)
            except Exception:
                imported, error = None, "This file could not be read."
            finally:
                spinner.set_visibility(False)
            if error:
                status.set_text(error)
                status.classes(add="text-negative")
                upload.reset()
                return
            found["imported"] = imported
            status.set_text(f"Ready: {e.file.name}")
            title.set_value(imported.title)
            plural = lambda n, word: f"{n} {word}{'' if n == 1 else 's'}"  # noqa: E731
            summary.set_text(f"{plural(imported.words, 'word')} · {plural(imported.headings, 'heading')} · "
                             f"{plural(imported.tables, 'table')}")
            notes_box.clear()
            with notes_box:
                for note in imported.notes:
                    ui.label(note).classes("ws-banner warn text-caption w-full")
            form.set_visibility(True)
            create.enable()

        def rejected(e) -> None:
            """The file picker refused the file before it was sent (wrong type or too large): say which."""
            entries = e.args if isinstance(e.args, list) else []
            first = entries[0] if entries and isinstance(entries[0], dict) else {}
            name = first.get("name", "")
            if first.get("reason") == "max-file-size":
                message = f"That file is too large (the limit is {MAX_BYTES // (1024 * 1024)} MB)."
            else:
                message = name_error(name) or "That file could not be accepted."
            status.set_text(message)
            status.classes(add="text-negative")
            form.set_visibility(False)
            create.disable()

        upload.on_upload(handle)
        # A browser File cannot be serialized, so pick out just the reason and the name in the browser.
        upload.on("rejected", rejected, js_handler="(entries) => emit(entries.map("
                  "(x) => ({reason: x.failedPropValidation, name: x.file ? x.file.name : ''})))")
        result = await dialog
        if not result:
            return
        imported, new_title, new_type = result
        async with busy(self.upload_button):
            created = await self.call(self.ctx.docs.create_document, self.actor, self.project.id,
                                      new_title or imported.title, new_type or "Imported", imported.html)
        if created is FAILED:
            return
        await self.reload_docs()
        await self.open_document(created.document.id)
        self.notify(f"Imported as a draft (version 1). You can edit it now.", type="positive")
        for note in imported.notes[:3]:
            self.notify(note, type="warning")

    async def toggle_published(self) -> None:
        v = self.view
        if v is None or v.document.published_version is None:
            return
        if self.mode == "published":
            await self.open_document(v.document.id)
        else:
            await self.open_document(v.document.id, v.document.published_version, mode="published")

    async def view_version(self, number: int) -> None:
        if number == self.view.document.current_version and DOC_READ_DRAFT in self.view.capabilities:
            await self.open_document(self.view.document.id)  # that is the latest draft: just go back to it
            return
        await self.open_document(self.view.document.id, number, mode="version")

    async def export(self, fmt: str) -> None:
        v = self.view
        if v is None:
            return
        self.notify("Preparing your export…", type="info")
        async with busy(self.export_btn):
            try:
                result = await self.ctx.exporter.export(self.actor, v.document.id, fmt, v.version_number, self.tz)
            except EditorError as exc:
                self.notify(exc.message, type="negative")
                return
            except Exception:
                self.notify("The export could not be created. Please try again.", type="negative")
                return
        ui.download.content(result.data, result.filename, result.media_type)
        self.notify(f"Exported {result.filename}", type="positive")

    # ------------------------------------------------------------------ diffs

    async def compare(self, number: int) -> None:
        v = self.view
        old = await self.call(self.ctx.docs.get, self.actor, v.document.id, number)
        new = await self.call(self.ctx.docs.get, self.actor, v.document.id, None)
        if old is FAILED or new is FAILED:
            return
        segments = diff_html(old.html, new.html)
        if not hunks(segments):
            self.notify(f"Version {number} and version {new.version_number} are identical.", type="info")
            return
        self._compare_note = f"Comparing version {number} with version {new.version_number}. Green was added, red was removed."
        self.in_diff, self.diff_kind = True, "compare"
        self.render_banners()
        self.refresh_controls()
        self.editor.show_diff([s.as_dict() for s in segments], False)

    async def show_agent_diff(self, segments: list[dict]) -> None:
        self.in_diff, self.diff_kind = True, "agent"
        self.render_banners()
        self.refresh_controls()
        self.editor.show_diff(segments, True)

    async def leave_diff(self, *, reload_latest: bool) -> None:
        self.editor.hide_diff()
        self.in_diff, self.diff_kind = False, None
        if reload_latest and self.view is not None:
            self.editor.dirty = False
            await self.open_document(self.view.document.id)
            await self.reload_docs()
        else:
            self.render_banners()
            self.refresh_controls()

    async def restore(self, number: int) -> None:
        v = self.view
        warning = "Its content becomes a new draft version. Nothing is deleted."
        if self.editor.dirty or self.stash is not None:
            warning += " Your unsaved edits in the current draft will be discarded."
        if not await self.confirm(f"Restore version {number}?", warning, "Restore"):
            return
        self.stash = self.base_override = None
        self.editor.dirty = False
        latest = v.document.current_version
        restored = await self.call(self.ctx.docs.restore, self.actor, v.document.id, number, latest)
        if restored is FAILED:
            return
        await self.open_document(v.document.id)
        await self.reload_docs()
        self.notify(f"Restored version {number} as version {restored.version_number} (draft)", type="positive")


def _esc(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def register(ctx: AppContext) -> None:
    @ui.page("/")
    async def workspace_page():
        known = personas(ctx)
        user_id = app.storage.user.get("user_id")
        if user_id not in known:
            user_id = next(iter(known), None)
            app.storage.user["user_id"] = user_id
        actor = await run.io_bound(ctx.authz.resolve_actor, user_id)
        if actor is None:
            ui.label("No demo users found. Start the app with demo data.").classes("ws-empty")
            return
        page_colors()
        ui.add_head_html("<style>.nicegui-content{padding:0}</style>")
        ws = Workspace(ctx, actor, None)
        ws.build()
        await ui.context.client.connected()
        try:
            ws.tz = await ui.run_javascript("Intl.DateTimeFormat().resolvedOptions().timeZone", timeout=5)
        except Exception:
            ws.tz = None
        await ws.init()
