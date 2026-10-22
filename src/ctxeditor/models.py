"""Plain records returned by the services, and the action catalogue codes this feature enforces."""
from __future__ import annotations

from dataclasses import dataclass, field

# Action codes (ERD style). The catalogue and the role matrix live in seed.py; no role name appears in any service.
DOC_READ = "doc.read"
DOC_READ_DRAFT = "doc.read_draft"
DOC_CREATE = "doc.create"
DOC_EDIT = "doc.edit"
DOC_PUBLISH = "doc.publish"
DOC_RESTORE = "doc.restore"
DOC_EXPORT = "doc.export"
DOC_EXPORT_DRAFT = "doc.export_draft"
DOC_COMMENT = "doc.comment"
COMMENT_RESOLVE = "comment.resolve"
AGENT_USE = "agent.use"

ACTION_CATALOGUE: tuple[tuple[str, str, str], ...] = (
    (DOC_READ, "project", "Read published versions"),
    (DOC_READ_DRAFT, "project", "Read unpublished versions"),
    (DOC_CREATE, "project", "Create documents"),
    (DOC_EDIT, "project", "Save draft versions"),
    (DOC_PUBLISH, "project", "Publish a version"),
    (DOC_RESTORE, "project", "Restore an older version as a new draft"),
    (DOC_EXPORT, "project", "Export published versions"),
    (DOC_EXPORT_DRAFT, "project", "Export the current draft"),
    (DOC_COMMENT, "project", "Comment, reply, and edit or delete own comments"),
    (COMMENT_RESOLVE, "project", "Resolve and reopen any comment"),
    (AGENT_USE, "project", "Use the AI editing agent"),
)


@dataclass(frozen=True)
class Actor:
    """The signed-in person. tenant_id comes from the server-side membership, never from the browser."""
    user_id: str
    tenant_id: str
    display_name: str


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    project_key: str


@dataclass(frozen=True)
class Document:
    id: str
    tenant_id: str
    project_id: str
    doc_type: str
    title: str
    current_version: int
    published_version: int | None
    created_by: str
    created_at: str
    updated_by: str
    updated_at: str
    published_by: str | None
    published_at: str | None


@dataclass(frozen=True)
class DocumentSummary:
    id: str
    title: str
    doc_type: str
    status: str  # "Draft" or "Published", for the latest version the caller may see
    current_version: int
    published_version: int | None
    updated_at: str


@dataclass(frozen=True)
class DocMetadata:
    """System-generated header. Never typed by hand and never stored inside content_html."""
    title: str
    doc_type: str
    version_number: int
    status: str  # "Draft" | "Published"
    created_at: str
    created_by: str
    last_edited_at: str
    last_edited_by: str
    last_published_at: str | None
    last_published_by: str | None


@dataclass(frozen=True)
class VersionInfo:
    version_number: int
    created_by: str
    created_at: str
    source: str
    published: bool
    change_note: str | None
    published_at: str | None
    restored_from_version: int | None


@dataclass(frozen=True)
class DocumentView:
    document: Document
    version_number: int
    html: str  # sanitized
    metadata: DocMetadata
    is_draft_view: bool  # the version shown has no publication
    editable: bool  # caller may save a new draft on top of this (it is the latest version)
    capabilities: frozenset[str]
    unchanged: bool = False


@dataclass(frozen=True)
class ExportPayload:
    html: str
    metadata: DocMetadata
    is_draft: bool
    title: str


@dataclass(frozen=True)
class Comment:
    id: str
    document_id: str
    version_number: int
    anchor_id: str | None
    quoted_text: str | None
    anchor_prefix: str | None
    anchor_suffix: str | None
    anchor_hint: int | None
    parent_comment_id: str | None
    author_id: str
    author_name: str
    author_role_code: str
    author_role_label: str
    body: str
    status: str
    created_at: str
    edited_at: str | None
    resolved_by: str | None
    resolved_at: str | None
    deleted: bool


@dataclass
class Thread:
    root: Comment
    replies: list[Comment] = field(default_factory=list)
