"""Server-level rules: draft invisibility, publish, versioning, optimistic locking, roles, tenants."""
from __future__ import annotations

import sqlite3

import pytest

from ctxeditor.errors import AlreadyPublished, NotFound, PermissionDenied, StaleVersion, ValidationFailed
from ctxeditor.migrate import applied_versions, rollback_last
from ctxeditor.sample_content import SAMPLE_HTML, SAMPLE_HTML_V2

TEAM = ("erin", "dmitri", "arjun", "sana")


def test_seed_state(env):
    view = env.docs.get(env.actor("priya"), env.doc_id)
    assert view.version_number == 2 and view.is_draft_view and view.editable
    assert view.document.published_version == 1


@pytest.mark.parametrize("who", TEAM)
def test_team_sees_only_published_version(env, who):
    view = env.docs.get(env.actor(who), env.doc_id)
    assert view.version_number == 1 and not view.is_draft_view and not view.editable
    assert "Open questions" not in view.html
    assert view.metadata.status == "Published"


@pytest.mark.parametrize("who", TEAM)
def test_team_cannot_request_the_draft(env, who):
    with pytest.raises(PermissionDenied):
        env.docs.get(env.actor(who), env.doc_id, version=2)


@pytest.mark.parametrize("who", TEAM)
def test_team_version_list_has_only_published(env, who):
    versions = env.docs.list_versions(env.actor(who), env.doc_id)
    assert [v.version_number for v in versions] == [1]
    assert all(v.published for v in versions)


def test_owner_version_list(env):
    versions = env.docs.list_versions(env.actor("priya"), env.doc_id)
    assert [(v.version_number, v.published) for v in versions] == [(2, False), (1, True)]


def test_unpublished_document_is_not_found_for_team(env):
    owner = env.actor("priya")
    created = env.docs.create_document(owner, env.seeded.projects["acme"], "Hidden", "Spec", "<p>secret draft</p>")
    for who in TEAM:
        with pytest.raises(NotFound):
            env.docs.get(env.actor(who), created.document.id)
        with pytest.raises(NotFound):
            env.docs.export_payload(env.actor(who), created.document.id)
        listed = env.docs.list_documents(env.actor(who), env.seeded.projects["acme"])
        assert created.document.id not in [d.id for d in listed]
    titles = [d.title for d in env.docs.list_documents(owner, env.seeded.projects["acme"])]
    assert "Hidden" in titles


def test_no_draft_bytes_in_any_team_read(env):
    owner = env.actor("priya")
    env.docs.save_draft(owner, env.doc_id, 2, "<p>TOP-SECRET-DRAFT-MARKER</p>")
    for who in TEAM:
        actor = env.actor(who)
        blobs = [env.docs.get(actor, env.doc_id).html]
        blobs += [repr(env.docs.list_versions(actor, env.doc_id))]
        blobs += [repr(env.docs.list_documents(actor, env.seeded.projects["acme"]))]
        blobs += [env.docs.export_payload(actor, env.doc_id).html]
        assert not any("TOP-SECRET-DRAFT-MARKER" in b for b in blobs)


def test_publish_makes_version_visible_and_later_drafts_stay_hidden(env):
    owner, team = env.actor("priya"), env.actor("dmitri")
    env.docs.publish(owner, env.doc_id, 2, "Add open questions")
    assert "Open questions" in env.docs.get(team, env.doc_id).html
    env.docs.save_draft(owner, env.doc_id, 2, "<p>v3 draft</p>")
    team_view = env.docs.get(team, env.doc_id)
    assert team_view.version_number == 2 and "v3 draft" not in team_view.html
    assert env.docs.get(owner, env.doc_id).version_number == 3


def test_publish_rules(env):
    owner = env.actor("priya")
    with pytest.raises(StaleVersion):
        env.docs.publish(owner, env.doc_id, 1)
    env.docs.publish(owner, env.doc_id, 2)
    with pytest.raises(AlreadyPublished):
        env.docs.publish(owner, env.doc_id, 2)


@pytest.mark.parametrize("who", TEAM)
def test_non_owner_cannot_edit_publish_restore_or_create(env, who):
    actor = env.actor(who)
    with pytest.raises(PermissionDenied):
        env.docs.save_draft(actor, env.doc_id, 1, "<p>x</p>")
    with pytest.raises((PermissionDenied, StaleVersion)):
        env.docs.publish(actor, env.doc_id, 2)
    with pytest.raises(PermissionDenied):
        env.docs.restore(actor, env.doc_id, 1, 2)
    with pytest.raises(PermissionDenied):
        env.docs.create_document(actor, env.seeded.projects["acme"], "T", "Spec")


def test_version_increments_and_metadata_updates_on_every_save(env):
    owner = env.actor("priya")
    first = env.docs.get(owner, env.doc_id)
    saved = env.docs.save_draft(owner, env.doc_id, first.version_number, "<p>one</p>")
    assert saved.version_number == first.version_number + 1
    assert saved.metadata.last_edited_by == "Priya Nair"
    assert saved.metadata.last_edited_at >= first.metadata.last_edited_at
    again = env.docs.save_draft(owner, env.doc_id, saved.version_number, "<p>two</p>")
    assert again.version_number == saved.version_number + 1


def test_unchanged_save_creates_no_version(env):
    owner = env.actor("priya")
    view = env.docs.get(owner, env.doc_id)
    result = env.docs.save_draft(owner, env.doc_id, view.version_number, view.html)
    assert result.unchanged and result.version_number == view.version_number


def test_stale_save_is_rejected(env):
    owner = env.actor("priya")
    env.docs.save_draft(owner, env.doc_id, 2, "<p>from tab one</p>")
    with pytest.raises(StaleVersion) as caught:
        env.docs.save_draft(owner, env.doc_id, 2, "<p>from tab two</p>")
    assert caught.value.current_version == 3
    assert "reload" in caught.value.message.lower()


def test_restore_creates_new_draft_and_keeps_history(env):
    owner = env.actor("priya")
    restored = env.docs.restore(owner, env.doc_id, 1, 2)
    assert restored.version_number == 3 and restored.is_draft_view
    assert "Open questions" not in restored.html
    versions = env.docs.list_versions(owner, env.doc_id)
    assert [v.version_number for v in versions] == [3, 2, 1]
    assert versions[0].source == "restore" and versions[0].restored_from_version == 1


def test_cross_tenant_and_unassigned_are_denied_as_not_found(env):
    for key in ("gwen", "una"):
        actor = env.actor(key)
        with pytest.raises(NotFound):
            env.docs.get(actor, env.doc_id)
        with pytest.raises(NotFound):
            env.docs.save_draft(actor, env.doc_id, 2, "<p>x</p>")
        with pytest.raises(NotFound):
            env.docs.publish(actor, env.doc_id, 2)
    with pytest.raises(NotFound):
        env.docs.list_documents(env.actor("gwen"), env.seeded.projects["acme"])
    with pytest.raises(NotFound):
        env.docs.create_document(env.actor("gwen"), env.seeded.projects["acme"], "T", "Spec")


def test_export_permissions(env):
    assert env.docs.export_payload(env.actor("sana"), env.doc_id).is_draft is False
    draft = env.docs.export_payload(env.actor("priya"), env.doc_id)
    assert draft.is_draft and draft.metadata.status == "Draft"
    with pytest.raises(PermissionDenied):
        env.docs.export_payload(env.actor("sana"), env.doc_id, version=2)


def test_title_and_type_validation(env):
    owner, project = env.actor("priya"), env.seeded.projects["acme"]
    with pytest.raises(ValidationFailed):
        env.docs.create_document(owner, project, "  ", "Spec")
    with pytest.raises(ValidationFailed):
        env.docs.create_document(owner, project, "T", "x" * 100)


def test_title_change_is_a_saved_version(env):
    owner = env.actor("priya")
    view = env.docs.get(owner, env.doc_id)
    renamed = env.docs.save_draft(owner, env.doc_id, view.version_number, view.html, title="New title")
    assert renamed.version_number == view.version_number + 1 and renamed.metadata.title == "New title"


def test_versions_and_audit_are_insert_only(env):
    with env.db.transaction() as conn:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("update document_versions set content_html = 'x'")
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("delete from audit_events")
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("update document_publications set change_note = 'x'")


def test_audit_events_hold_no_content(env):
    owner = env.actor("priya")
    env.docs.save_draft(owner, env.doc_id, 2, "<p>SENSITIVE-BODY-TEXT</p>")
    env.docs.publish(owner, env.doc_id, 3, "SENSITIVE-NOTE-TEXT")
    with env.db.read() as conn:
        rows = conn.execute("select action, metadata from audit_events").fetchall()
    actions = {r["action"] for r in rows}
    assert {"doc_created", "doc_draft_saved", "doc_published"} <= actions
    assert not any("SENSITIVE" in r["metadata"] for r in rows)


def test_capabilities_reflect_matrix_not_role_names(env):
    owner_caps = env.docs.capabilities(env.actor("priya"), env.seeded.projects["acme"])
    team_caps = env.docs.capabilities(env.actor("sana"), env.seeded.projects["acme"])
    assert "doc.publish" in owner_caps and "doc.publish" not in team_caps
    assert "doc.comment" in team_caps


def test_migration_rollback_roundtrip(tmp_path):
    from ctxeditor.db import Database
    from ctxeditor.migrate import migrate
    db = Database(tmp_path / "m.db")
    assert migrate(db) == ["0001_context_editor"]
    assert rollback_last(db) == "0001_context_editor"
    assert applied_versions(db) == []
    assert migrate(db) == ["0001_context_editor"]


def test_sample_content_is_stable_under_sanitizer():
    from ctxeditor.sanitizer import sanitize_html
    for html in (SAMPLE_HTML, SAMPLE_HTML_V2):
        assert sanitize_html(html) == html
