"""Documents, versions, publishing. Every method resolves the caller's actions through the role-action matrix and
enforces them here, on the server. The browser's read-only editor is a convenience, not security.

Visibility rules:
- A caller who holds doc.read_draft sees every version (the product owner's capability, granted by the role matrix).
- Any other caller with doc.read sees only the latest published version. A document with no published version is
  NotFound for them (same as a missing id); an explicit unpublished version is PermissionDenied.
"""
from __future__ import annotations

import hashlib
import json
import uuid

from .authz import AuthzService
from .db import Database
from .errors import AlreadyPublished, NotFound, PermissionDenied, StaleVersion, ValidationFailed
from .models import (
    AGENT_USE,
    DOC_CREATE,
    DOC_EDIT,
    DOC_EXPORT,
    DOC_EXPORT_DRAFT,
    DOC_PUBLISH,
    DOC_READ,
    DOC_READ_DRAFT,
    DOC_RESTORE,
    Actor,
    DocMetadata,
    Document,
    DocumentSummary,
    DocumentView,
    ExportPayload,
    VersionInfo,
)
from .sanitizer import sanitize_html
from .timefmt import utc_now_iso

MAX_TITLE = 200
MAX_TYPE = 60
MAX_NOTE = 1000


def content_hash(html: str) -> str:
    return hashlib.sha256(html.encode("utf-8")).hexdigest()


def _doc(row) -> Document:
    return Document(**{k: row[k] for k in Document.__dataclass_fields__})


class DocumentService:
    def __init__(self, db: Database, authz: AuthzService):
        self._db, self._authz = db, authz

    # ------------------------------------------------------------------ helpers

    def _audit(self, conn, actor: Actor, project_id: str, action: str, subject_id: str, **meta) -> None:
        conn.execute(
            "insert into audit_events (id, tenant_id, project_id, actor_id, action, subject_id, metadata, occurred_at)"
            " values (?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), actor.tenant_id, project_id, actor.user_id, action, subject_id,
             json.dumps(meta), utc_now_iso()))

    def _load(self, conn, actor: Actor, document_id: str):
        """The document row and the caller's actions at its project. NotFound across tenants, for unassigned
        projects, and for a document with no published version when the caller cannot read drafts."""
        row = conn.execute("select * from documents where id = ?", (document_id,)).fetchone()
        if row is None or row["tenant_id"] != actor.tenant_id:
            raise NotFound()
        actions = self._authz.actions_for(actor, row["project_id"], conn)
        if DOC_READ_DRAFT in actions:
            return row, actions
        if DOC_READ not in actions or row["published_version"] is None:
            raise NotFound()
        return row, actions

    @staticmethod
    def _names(conn, *user_ids: str | None) -> dict[str | None, str]:
        ids = [u for u in set(user_ids) if u]
        if not ids:
            return {None: "-"}
        marks = ",".join("?" * len(ids))
        found = {r["id"]: r["display_name"] for r in conn.execute(
            f"select id, display_name from users where id in ({marks})", ids)}
        found[None] = "-"
        return found

    def _metadata(self, conn, doc, version_row, published: bool) -> DocMetadata:
        names = self._names(conn, doc["created_by"], version_row["created_by"], doc["published_by"])
        return DocMetadata(
            title=doc["title"], doc_type=doc["doc_type"], version_number=version_row["version_number"],
            status="Published" if published else "Draft",
            created_at=doc["created_at"], created_by=names[doc["created_by"]],
            last_edited_at=version_row["created_at"], last_edited_by=names[version_row["created_by"]],
            last_published_at=doc["published_at"], last_published_by=names[doc["published_by"]])

    def _view(self, conn, doc, actions, version: int | None, *, unchanged: bool = False) -> DocumentView:
        can_draft = DOC_READ_DRAFT in actions
        if version is None:
            version = doc["current_version"] if can_draft else doc["published_version"]
        elif not can_draft and version != doc["published_version"]:
            raise PermissionDenied("Only the latest published version is available to you.")
        row = conn.execute("select * from document_versions where document_id = ? and version_number = ?",
                           (doc["id"], version)).fetchone()
        if row is None:
            raise NotFound()
        published = conn.execute("select 1 from document_publications where document_id = ? and version_number = ?",
                                 (doc["id"], version)).fetchone() is not None
        return DocumentView(
            document=_doc(doc), version_number=version, html=sanitize_html(row["content_html"]),
            metadata=self._metadata(conn, doc, row, published), is_draft_view=not published,
            editable=DOC_EDIT in actions and version == doc["current_version"],
            capabilities=actions, unchanged=unchanged)

    # ------------------------------------------------------------------ reads

    def capabilities(self, actor: Actor, project_id: str) -> frozenset[str]:
        """For showing and hiding controls only. Every write is checked again by the method that performs it."""
        self._authz.require_project(actor, project_id)
        return self._authz.actions_for(actor, project_id)

    def can_create(self, actor: Actor, project_id: str) -> bool:
        """Cheap pre-check (for example before converting an upload). create_document enforces it again."""
        self._authz.require_project(actor, project_id)
        return self._authz.can(actor, DOC_CREATE, project_id)

    def list_documents(self, actor: Actor, project_id: str) -> list[DocumentSummary]:
        self._authz.require_project(actor, project_id)
        with self._db.read() as conn:
            actions = self._authz.actions_for(actor, project_id, conn)
            can_draft = DOC_READ_DRAFT in actions
            if not can_draft and DOC_READ not in actions:
                return []
            rows = conn.execute(
                "select * from documents where project_id = ? and tenant_id = ? order by lower(title)",
                (project_id, actor.tenant_id)).fetchall()
        out = []
        for r in rows:
            if not can_draft and r["published_version"] is None:
                continue
            latest = r["current_version"] if can_draft else r["published_version"]
            out.append(DocumentSummary(
                id=r["id"], title=r["title"], doc_type=r["doc_type"],
                status="Published" if r["published_version"] == latest else "Draft",
                current_version=r["current_version"], published_version=r["published_version"],
                updated_at=r["updated_at"]))
        return out

    def get(self, actor: Actor, document_id: str, version: int | None = None) -> DocumentView:
        with self._db.read() as conn:
            doc, actions = self._load(conn, actor, document_id)
            return self._view(conn, doc, actions, version)

    def list_versions(self, actor: Actor, document_id: str) -> list[VersionInfo]:
        with self._db.read() as conn:
            doc, actions = self._load(conn, actor, document_id)
            rows = conn.execute(
                """select v.version_number, v.created_by, v.created_at, v.source, v.restored_from_version,
                          p.version_number as pub, p.change_note, p.published_at
                   from document_versions v
                   left join document_publications p
                     on p.document_id = v.document_id and p.version_number = v.version_number
                   where v.document_id = ? order by v.version_number desc""", (document_id,)).fetchall()
            names = self._names(conn, *[r["created_by"] for r in rows])
        can_draft = DOC_READ_DRAFT in actions
        return [VersionInfo(
            version_number=r["version_number"], created_by=names[r["created_by"]], created_at=r["created_at"],
            source=r["source"], published=r["pub"] is not None, change_note=r["change_note"],
            published_at=r["published_at"], restored_from_version=r["restored_from_version"])
            for r in rows if can_draft or r["version_number"] == doc["published_version"]]

    # ------------------------------------------------------------------ writes

    def create_document(self, actor: Actor, project_id: str, title: str, doc_type: str, html: str = "") -> DocumentView:
        title, doc_type = (title or "").strip(), (doc_type or "").strip()
        if not title or len(title) > MAX_TITLE:
            raise ValidationFailed(f"Enter a title of 1 to {MAX_TITLE} characters", field="title")
        if not doc_type or len(doc_type) > MAX_TYPE:
            raise ValidationFailed(f"Enter a document type of 1 to {MAX_TYPE} characters", field="doc_type")
        clean = sanitize_html(html)
        self._authz.require_project(actor, project_id)
        now, doc_id = utc_now_iso(), str(uuid.uuid4())
        with self._db.transaction() as conn:
            self._authz.require(actor, DOC_CREATE, project_id, conn)
            conn.execute(
                "insert into documents (id, tenant_id, project_id, doc_type, title, current_version, created_by,"
                " created_at, updated_by, updated_at) values (?,?,?,?,?,1,?,?,?,?)",
                (doc_id, actor.tenant_id, project_id, doc_type, title, actor.user_id, now, actor.user_id, now))
            self._insert_version(conn, actor, doc_id, project_id, 1, clean, "manual", now)
            self._audit(conn, actor, project_id, "doc_created", doc_id, doc_type=doc_type)
        return self.get(actor, doc_id)

    def _insert_version(self, conn, actor, doc_id, project_id, number, html, source, now,
                        restored_from=None, agent_request_id=None) -> None:
        conn.execute(
            "insert into document_versions (id, tenant_id, project_id, document_id, version_number, content_html,"
            " content_hash, source, restored_from_version, agent_request_id, created_by, created_at)"
            " values (?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), actor.tenant_id, project_id, doc_id, number, html, content_hash(html), source,
             restored_from, agent_request_id, actor.user_id, now))

    def save_draft(self, actor: Actor, document_id: str, expected_version: int, html: str, *,
                   source: str = "manual", agent_request_id: str | None = None,
                   restored_from: int | None = None, title: str | None = None) -> DocumentView:
        """Save html (and optionally a new title) as the next version. Rejected with StaleVersion when the
        document moved on since the caller loaded expected_version. A manual save that changes neither the content
        nor the title returns the current view and creates nothing."""
        clean = sanitize_html(html)
        if title is not None:
            title = title.strip()
            if not title or len(title) > MAX_TITLE:
                raise ValidationFailed(f"Enter a title of 1 to {MAX_TITLE} characters", field="title")
        with self._db.transaction() as conn:
            doc, actions = self._load(conn, actor, document_id)
            if DOC_EDIT not in actions:
                raise PermissionDenied()
            if source == "agent" and AGENT_USE not in actions:
                raise PermissionDenied()
            if source == "restore" and DOC_RESTORE not in actions:
                raise PermissionDenied()
            if doc["current_version"] != expected_version:
                raise StaleVersion(doc["current_version"])
            if source == "manual" and title in (None, doc["title"]):
                current = conn.execute(
                    "select content_hash from document_versions where document_id=? and version_number=?",
                    (document_id, expected_version)).fetchone()
                if current["content_hash"] == content_hash(clean):
                    return self._view(conn, doc, actions, expected_version, unchanged=True)
            now, number = utc_now_iso(), expected_version + 1
            updated = conn.execute(
                "update documents set current_version = ?, updated_by = ?, updated_at = ?, title = coalesce(?, title) "
                "where id = ? and current_version = ?",
                (number, actor.user_id, now, title, document_id, expected_version))
            if updated.rowcount != 1:
                raise StaleVersion(doc["current_version"])
            self._insert_version(conn, actor, document_id, doc["project_id"], number, clean, source, now,
                                 restored_from, agent_request_id)
            self._audit(conn, actor, doc["project_id"], "doc_draft_saved", document_id, version=number,
                        source=source, hash=content_hash(clean))
            fresh = conn.execute("select * from documents where id = ?", (document_id,)).fetchone()
            return self._view(conn, fresh, actions, number)

    def publish(self, actor: Actor, document_id: str, version: int, change_note: str | None = None) -> DocumentView:
        note = (change_note or "").strip() or None
        if note and len(note) > MAX_NOTE:
            raise ValidationFailed(f"The change note can be {MAX_NOTE} characters at most", field="change_note")
        with self._db.transaction() as conn:
            doc, actions = self._load(conn, actor, document_id)
            if DOC_PUBLISH not in actions:
                raise PermissionDenied()
            if doc["current_version"] != version:
                raise StaleVersion(doc["current_version"])
            if doc["published_version"] == version:
                raise AlreadyPublished()
            now = utc_now_iso()
            conn.execute(
                "insert into document_publications (id, tenant_id, project_id, document_id, version_number,"
                " change_note, published_by, published_at) values (?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), actor.tenant_id, doc["project_id"], document_id, version, note,
                 actor.user_id, now))
            conn.execute("update documents set published_version = ?, published_by = ?, published_at = ? "
                         "where id = ? and current_version = ?", (version, actor.user_id, now, document_id, version))
            self._audit(conn, actor, doc["project_id"], "doc_published", document_id, version=version,
                        has_note=bool(note))
            fresh = conn.execute("select * from documents where id = ?", (document_id,)).fetchone()
            return self._view(conn, fresh, actions, version)

    def restore(self, actor: Actor, document_id: str, from_version: int, expected_version: int) -> DocumentView:
        """Copy an older version's content into a new draft version. History is never rewritten."""
        with self._db.read() as conn:
            doc, actions = self._load(conn, actor, document_id)
            if DOC_RESTORE not in actions or DOC_READ_DRAFT not in actions:
                raise PermissionDenied()
            row = conn.execute("select content_html from document_versions where document_id=? and version_number=?",
                               (document_id, from_version)).fetchone()
            if row is None:
                raise NotFound()
            html = row["content_html"]
        view = self.save_draft(actor, document_id, expected_version, html, source="restore",
                               restored_from=from_version)
        with self._db.transaction() as conn:
            self._audit(conn, actor, view.document.project_id, "doc_restored", document_id,
                        from_version=from_version, new_version=view.version_number)
        return view

    # ------------------------------------------------------------------ export

    def export_payload(self, actor: Actor, document_id: str, version: int | None = None,
                       fmt: str = "pdf") -> ExportPayload:
        """What an export is built from. Draft content needs doc.export_draft; published content needs doc.export.
        The export itself is audited here, so no export can bypass the check."""
        with self._db.transaction() as conn:
            doc, actions = self._load(conn, actor, document_id)
            can_draft = DOC_READ_DRAFT in actions
            view = self._view(conn, doc, actions, version)
            needed = DOC_EXPORT_DRAFT if view.is_draft_view else DOC_EXPORT
            if needed not in actions or (view.is_draft_view and not can_draft):
                raise PermissionDenied()
            self._audit(conn, actor, doc["project_id"], "doc_exported", document_id,
                        version=view.version_number, format=fmt, draft=view.is_draft_view)
        return ExportPayload(html=view.html, metadata=view.metadata, is_draft=view.is_draft_view,
                             title=view.metadata.title)
