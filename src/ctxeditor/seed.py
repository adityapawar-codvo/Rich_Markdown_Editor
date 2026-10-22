"""Demo data: two tenants, one project each, one person per role, and one sample document that exercises every
editor feature. This is the only place role names appear; services check actions only."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .authz import AuthzService
from .db import Database
from .documents import DocumentService
from .models import (
    ACTION_CATALOGUE,
    AGENT_USE,
    COMMENT_RESOLVE,
    DOC_COMMENT,
    DOC_CREATE,
    DOC_EDIT,
    DOC_EXPORT,
    DOC_EXPORT_DRAFT,
    DOC_PUBLISH,
    DOC_READ,
    DOC_READ_DRAFT,
    DOC_RESTORE,
)
from .sample_content import SAMPLE_HTML, SAMPLE_HTML_V2

ALL_PRODUCT_OWNER = (DOC_READ, DOC_READ_DRAFT, DOC_CREATE, DOC_EDIT, DOC_PUBLISH, DOC_RESTORE, DOC_EXPORT,
                     DOC_EXPORT_DRAFT, DOC_COMMENT, COMMENT_RESOLVE, AGENT_USE)
TEAM_MEMBER = (DOC_READ, DOC_COMMENT, DOC_EXPORT)

ROLES = {  # code -> (name, actions)
    "product_owner": ("Product Owner", ALL_PRODUCT_OWNER),
    "executive": ("Executive", TEAM_MEMBER),
    "developer": ("Developer", TEAM_MEMBER),
    "architect": ("Architect", TEAM_MEMBER),
    "qa": ("QA", TEAM_MEMBER),
}

# key -> (display name, email, tenant key, role code or None)
PEOPLE = {
    "priya": ("Priya Nair", "priya@acme.example", "acme", "product_owner"),
    "erin": ("Erin Walsh", "erin@acme.example", "acme", "executive"),
    "dmitri": ("Dmitri Volkov", "dmitri@acme.example", "acme", "developer"),
    "arjun": ("Arjun Mehta", "arjun@acme.example", "acme", "architect"),
    "sana": ("Sana Okafor", "sana@acme.example", "acme", "qa"),
    "una": ("Una Unassigned", "una@acme.example", "acme", None),
    "gwen": ("Gwen Park", "gwen@globex.example", "globex", "product_owner"),
}


@dataclass
class Seeded:
    tenants: dict[str, str] = field(default_factory=dict)
    projects: dict[str, str] = field(default_factory=dict)  # tenant key -> project id
    users: dict[str, str] = field(default_factory=dict)  # person key -> user id
    roles: dict[tuple[str, str], str] = field(default_factory=dict)  # (tenant key, role code) -> role id
    document_id: str | None = None


def _id() -> str:
    return str(uuid.uuid4())


def seed(db: Database, *, sample_document: bool = True) -> Seeded:
    out = Seeded()
    with db.transaction() as conn:
        action_ids = {}
        for code, scope, description in ACTION_CATALOGUE:
            action_ids[code] = _id()
            conn.execute("insert into actions values (?,?,?,?)", (action_ids[code], code, scope, description))
        for key, name in (("acme", "Acme Corp"), ("globex", "Globex Inc")):
            tenant_id = out.tenants[key] = _id()
            conn.execute("insert into tenants values (?,?,?)", (tenant_id, name, key))
            project_id = out.projects[key] = _id()
            conn.execute("insert into projects values (?,?,?,?)",
                         (project_id, tenant_id, "Customer Portal" if key == "acme" else "Supply Planner",
                          "CP" if key == "acme" else "SP"))
            for code, (role_name, actions) in ROLES.items():
                role_id = out.roles[(key, code)] = _id()
                conn.execute("insert into roles values (?,?,?,?)", (role_id, tenant_id, code, role_name))
                for action in actions:
                    conn.execute("insert into role_actions values (?,?,?)", (tenant_id, role_id, action_ids[action]))
        for key, (display, email, tenant_key, role_code) in PEOPLE.items():
            user_id = out.users[key] = _id()
            tenant_id = out.tenants[tenant_key]
            conn.execute("insert into users values (?,?,?,?)", (user_id, tenant_id, email, display))
            membership_id = _id()
            conn.execute("insert into memberships values (?,?,?,'active')", (membership_id, tenant_id, user_id))
            if role_code:
                conn.execute("insert into membership_roles values (?,?,?,?,null)",
                             (tenant_id, membership_id, out.roles[(tenant_key, role_code)], out.projects[tenant_key]))
    if sample_document:
        authz = AuthzService(db)
        service = DocumentService(db, authz)
        priya = authz.resolve_actor(out.users["priya"])
        view = service.create_document(priya, out.projects["acme"], "Context editor showcase", "Guide", SAMPLE_HTML)
        service.publish(priya, view.document.id, 1, "Initial version")
        service.save_draft(priya, view.document.id, 1, SAMPLE_HTML_V2)  # a newer draft the team cannot see
        out.document_id = view.document.id
    return out
