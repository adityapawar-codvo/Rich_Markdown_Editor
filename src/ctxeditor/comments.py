"""Comments and annotations. Server-side rules:

- Anyone who can read the document and holds doc.comment can comment and reply (one reply level).
- Authors edit or delete their own comments. Delete is soft: the row and audit trail stay, the body is hidden.
- Holders of comment.resolve resolve and reopen any thread (root comments only).
- Comments made on a version newer than the latest published one (the owner's draft) are invisible to callers who
  cannot read drafts. Replies follow their thread: an owner's reply to a team comment is visible to the team even
  when it was written while viewing the draft.
- Anchors are text-quote selectors stored on the row. The editor draws the highlight, so the document never changes.
  Whether the text is still present in a version is decided by the editor when it resolves the anchor.
"""
from __future__ import annotations

import uuid

from .authz import AuthzService
from .db import Database
from .documents import DocumentService
from .errors import NotFound, PermissionDenied, ValidationFailed
from .models import (
    AGENT_USE,
    COMMENT_RESOLVE,
    DOC_COMMENT,
    DOC_READ_DRAFT,
    Actor,
    Comment,
    Thread,
)
from .timefmt import utc_now_iso

MAX_BODY = 5000
MAX_QUOTE = 2000
MAX_CONTEXT = 64


def _comment(row) -> Comment:
    deleted = row["deleted_at"] is not None
    return Comment(
        id=row["id"], document_id=row["document_id"], version_number=row["version_number"],
        anchor_id=row["anchor_id"], quoted_text=row["quoted_text"], anchor_prefix=row["anchor_prefix"],
        anchor_suffix=row["anchor_suffix"], anchor_hint=row["anchor_hint"],
        parent_comment_id=row["parent_comment_id"], author_id=row["author_id"], author_name=row["author_name"],
        author_role_code=row["author_role_code"], author_role_label=row["author_role_label"],
        body="" if deleted else row["body"], status=row["status"], created_at=row["created_at"],
        edited_at=row["edited_at"], resolved_by=row["resolved_by"], resolved_at=row["resolved_at"], deleted=deleted)


_SELECT = ("select c.*, u.display_name as author_name from comments c join users u on u.id = c.author_id ")


class CommentService:
    def __init__(self, db: Database, authz: AuthzService, docs: DocumentService):
        self._db, self._authz, self._docs = db, authz, docs

    def _doc(self, conn, actor: Actor, document_id: str):
        doc, actions = self._docs._load(conn, actor, document_id)  # NotFound rules are shared with documents
        return doc, actions

    @staticmethod
    def _body(body: str) -> str:
        body = (body or "").strip()
        if not body or len(body) > MAX_BODY:
            raise ValidationFailed(f"Write a comment of 1 to {MAX_BODY} characters", field="body")
        return body

    def list_threads(self, actor: Actor, document_id: str, status: str = "all") -> list[Thread]:
        """Threads (root + replies) oldest first. status: all | open | resolved."""
        with self._db.read() as conn:
            doc, actions = self._doc(conn, actor, document_id)
            rows = conn.execute(_SELECT + "where c.document_id = ? order by c.created_at, c.rowid",
                                (document_id,)).fetchall()
        can_draft = DOC_READ_DRAFT in actions
        limit = doc["current_version"] if can_draft else doc["published_version"]
        threads: dict[str, Thread] = {}
        replies: list[Comment] = []
        for row in rows:
            comment = _comment(row)
            if comment.parent_comment_id is None:
                if row["version_number"] <= limit:  # a root made on an unpublished draft stays hidden from the team
                    threads[comment.id] = Thread(comment)
            else:
                replies.append(comment)  # a reply is visible whenever its thread is, whatever version it was written on
        for reply in replies:
            if reply.parent_comment_id in threads:
                threads[reply.parent_comment_id].replies.append(reply)
        result = list(threads.values())
        if status in ("open", "resolved"):
            result = [t for t in result if t.root.status == status]
        # A deleted root with no remaining visible replies disappears; with replies it stays as a tombstone.
        return [t for t in result if not (t.root.deleted and not any(not r.deleted for r in t.replies))]

    def add(self, actor: Actor, document_id: str, version_number: int, body: str, *,
            anchor: dict | None = None, parent_id: str | None = None) -> Comment:
        """anchor: {quote, prefix, suffix, hint} for text comments; None for General comments and replies."""
        body = self._body(body)
        if parent_id is not None and anchor is not None:
            raise ValidationFailed("A reply cannot have its own anchor")
        quote = prefix = suffix = anchor_id = hint = None
        if anchor is not None:
            quote = str(anchor.get("quote") or "")
            if not quote.strip() or len(quote) > MAX_QUOTE:
                raise ValidationFailed("Select some text to comment on")
            prefix = str(anchor.get("prefix") or "")[-MAX_CONTEXT:]
            suffix = str(anchor.get("suffix") or "")[:MAX_CONTEXT]
            hint = max(0, int(anchor.get("hint") or 0))
            anchor_id = str(uuid.uuid4())
        with self._db.transaction() as conn:
            doc, actions = self._doc(conn, actor, document_id)
            if DOC_COMMENT not in actions:
                raise PermissionDenied()
            readable = doc["current_version"] if DOC_READ_DRAFT in actions else doc["published_version"]
            if not 1 <= version_number <= readable:
                raise ValidationFailed("That version is not available for comments")
            if parent_id is not None:
                parent = conn.execute("select document_id, parent_comment_id, deleted_at from comments where id = ?",
                                      (parent_id,)).fetchone()
                if parent is None or parent["document_id"] != document_id:
                    raise NotFound()
                if parent["parent_comment_id"] is not None:
                    raise ValidationFailed("Replies can only be added to a top-level comment")
            role_code, role_label = self._authz.role_badge(actor, doc["project_id"], conn)
            comment_id = str(uuid.uuid4())
            conn.execute(
                "insert into comments (id, tenant_id, project_id, document_id, version_number, anchor_id, quoted_text,"
                " anchor_prefix, anchor_suffix, anchor_hint, parent_comment_id, author_id, author_role_code,"
                " author_role_label, body, status, created_at) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'open',?)",
                (comment_id, actor.tenant_id, doc["project_id"], document_id, version_number, anchor_id, quote,
                 prefix, suffix, hint, parent_id, actor.user_id, role_code, role_label, body, utc_now_iso()))
            self._docs._audit(conn, actor, doc["project_id"], "comment_added", comment_id,
                              document_id=document_id, version=version_number, reply=parent_id is not None)
            return _comment(conn.execute(_SELECT + "where c.id = ?", (comment_id,)).fetchone())

    def _own(self, conn, actor: Actor, comment_id: str):
        row = conn.execute("select * from comments where id = ?", (comment_id,)).fetchone()
        if row is None or row["tenant_id"] != actor.tenant_id:
            raise NotFound()
        doc, actions = self._doc(conn, actor, row["document_id"])
        return row, doc, actions

    def edit(self, actor: Actor, comment_id: str, body: str) -> Comment:
        body = self._body(body)
        with self._db.transaction() as conn:
            row, doc, actions = self._own(conn, actor, comment_id)
            if row["author_id"] != actor.user_id or DOC_COMMENT not in actions or row["deleted_at"]:
                raise PermissionDenied()
            conn.execute("update comments set body = ?, edited_at = ? where id = ?",
                         (body, utc_now_iso(), comment_id))
            self._docs._audit(conn, actor, doc["project_id"], "comment_edited", comment_id)
            return _comment(conn.execute(_SELECT + "where c.id = ?", (comment_id,)).fetchone())

    def delete(self, actor: Actor, comment_id: str) -> None:
        """Soft delete: nothing is removed silently. The body is hidden from every view; the audit trail remains."""
        with self._db.transaction() as conn:
            row, doc, actions = self._own(conn, actor, comment_id)
            if row["author_id"] != actor.user_id or DOC_COMMENT not in actions:
                raise PermissionDenied()
            if row["deleted_at"]:
                return
            conn.execute("update comments set deleted_at = ? where id = ?", (utc_now_iso(), comment_id))
            self._docs._audit(conn, actor, doc["project_id"], "comment_deleted", comment_id)

    def set_resolved(self, actor: Actor, comment_id: str, resolved: bool) -> Comment:
        with self._db.transaction() as conn:
            row, doc, actions = self._own(conn, actor, comment_id)
            if COMMENT_RESOLVE not in actions:
                raise PermissionDenied()
            if row["parent_comment_id"] is not None:
                raise ValidationFailed("Resolve the top-level comment of the thread")
            if resolved:
                conn.execute("update comments set status='resolved', resolved_by=?, resolved_at=? where id=?",
                             (actor.user_id, utc_now_iso(), comment_id))
            else:
                conn.execute("update comments set status='open', resolved_by=null, resolved_at=null where id=?",
                             (comment_id,))
            self._docs._audit(conn, actor, doc["project_id"], "comment_resolved" if resolved else "comment_reopened",
                              comment_id)
            return _comment(conn.execute(_SELECT + "where c.id = ?", (comment_id,)).fetchone())

    def open_count(self, actor: Actor, document_id: str) -> int:
        return len(self.list_threads(actor, document_id, "open"))

    def threads_for_agent(self, actor: Actor, document_id: str, comment_ids: list[str]) -> list[Thread]:
        """The open threads the product owner selected for the agent. Needs agent.use."""
        with self._db.read() as conn:
            _, actions = self._doc(conn, actor, document_id)
        if AGENT_USE not in actions:
            raise PermissionDenied()
        wanted = set(comment_ids)
        return [t for t in self.list_threads(actor, document_id, "open") if t.root.id in wanted]
