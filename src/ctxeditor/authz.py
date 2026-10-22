"""Authorization through the role-action matrix. No role name is tested anywhere in this package."""
from __future__ import annotations

from .db import Database
from .errors import NotFound, PermissionDenied
from .models import Actor, Project
from .timefmt import utc_now_iso


class AuthzService:
    def __init__(self, db: Database):
        self._db = db

    def resolve_actor(self, user_id: str) -> Actor | None:
        """The actor for a user with an active membership. The tenant is read from the membership."""
        if not user_id:
            return None
        with self._db.read() as conn:
            row = conn.execute(
                "select u.id, u.display_name, m.tenant_id from users u join memberships m on m.user_id = u.id "
                "where u.id = ? and m.status = 'active'", (user_id,)).fetchone()
        return Actor(row["id"], row["tenant_id"], row["display_name"]) if row else None

    def _grants(self, conn, actor: Actor, project_id: str | None):
        """(role code, role name, action code) the actor holds at this project. An organization-wide assignment
        contributes only actions whose allowed_scope is organization or any; a project assignment contributes
        project or any. This is the ERD rule that a role grants only scope-compatible actions."""
        return conn.execute(
            """
            select r.code as role_code, r.name as role_name, a.code as action_code
            from memberships m
            join membership_roles mr on mr.membership_id = m.id and mr.tenant_id = m.tenant_id
            join roles r on r.id = mr.role_id and r.tenant_id = m.tenant_id
            join role_actions ra on ra.role_id = r.id and ra.tenant_id = m.tenant_id
            join actions a on a.id = ra.action_id
            where m.user_id = :user and m.tenant_id = :tenant and m.status = 'active'
              and (mr.expires_at is null or mr.expires_at > :now)
              and (
                (mr.project_id is null and a.allowed_scope in ('organization', 'any'))
                or (mr.project_id = :project and a.allowed_scope in ('project', 'any'))
              )
              and (:project is null or exists (
                    select 1 from projects p where p.id = :project and p.tenant_id = m.tenant_id))
            order by r.name, a.code
            """,
            {"user": actor.user_id, "tenant": actor.tenant_id, "project": project_id, "now": utc_now_iso()},
        ).fetchall()

    def actions_for(self, actor: Actor, project_id: str, conn=None) -> frozenset[str]:
        """Pass conn to evaluate inside the caller's write transaction."""
        if conn is not None:
            return frozenset(r["action_code"] for r in self._grants(conn, actor, project_id))
        with self._db.read() as own:
            return frozenset(r["action_code"] for r in self._grants(own, actor, project_id))

    def can(self, actor: Actor, action: str, project_id: str, conn=None) -> bool:
        return action in self.actions_for(actor, project_id, conn)

    def require(self, actor: Actor, action: str, project_id: str, conn=None) -> None:
        if not self.can(actor, action, project_id, conn):
            raise PermissionDenied()

    def role_badge(self, actor: Actor, project_id: str, conn=None) -> tuple[str, str]:
        """(code, label) of the role shown next to the actor's comments. Taken from the role assignment at write
        time, never from the client. With several roles the alphabetically first by name is used."""
        def pick(c):
            rows = self._grants(c, actor, project_id)
            return (rows[0]["role_code"], rows[0]["role_name"]) if rows else None
        if conn is not None:
            found = pick(conn)
        else:
            with self._db.read() as own:
                found = pick(own)
        if found is None:
            raise PermissionDenied()
        return found

    def list_projects(self, actor: Actor) -> list[Project]:
        """Projects of the actor's tenant on which the actor holds at least one role."""
        with self._db.read() as conn:
            rows = conn.execute(
                """
                select distinct p.id, p.name, p.project_key from projects p
                join memberships m on m.tenant_id = p.tenant_id and m.user_id = :user and m.status = 'active'
                join membership_roles mr on mr.membership_id = m.id
                where p.tenant_id = :tenant and (mr.project_id = p.id or mr.project_id is null)
                  and (mr.expires_at is null or mr.expires_at > :now)
                order by p.name
                """, {"user": actor.user_id, "tenant": actor.tenant_id, "now": utc_now_iso()}).fetchall()
        return [Project(r["id"], r["name"], r["project_key"]) for r in rows]

    def require_project(self, actor: Actor, project_id: str) -> None:
        """NotFound (not PermissionDenied) when the project is not the actor's, so existence is not leaked."""
        if not any(p.id == project_id for p in self.list_projects(actor)):
            raise NotFound()
