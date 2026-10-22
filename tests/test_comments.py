from __future__ import annotations

import pytest

from ctxeditor.comments import CommentService
from ctxeditor.errors import NotFound, PermissionDenied, ValidationFailed

ANCHOR = {"quote": "Vendor lock-in", "prefix": "Risk Impact Mitigation ", "suffix": " High", "hint": 120}


@pytest.fixture
def comments(env) -> CommentService:
    return CommentService(env.db, env.authz, env.docs)


def test_team_member_comments_with_role_badge_and_version(env, comments):
    c = comments.add(env.actor("sana"), env.doc_id, 1, "Is this covered by tests?", anchor=ANCHOR)
    assert c.author_role_label == "QA" and c.version_number == 1 and c.anchor_id and c.status == "open"
    assert c.quoted_text == "Vendor lock-in" and c.edited_at is None


def test_general_comment_has_no_anchor(env, comments):
    c = comments.add(env.actor("arjun"), env.doc_id, 1, "General thought")
    assert c.anchor_id is None and c.quoted_text is None


def test_one_level_of_replies(env, comments):
    root = comments.add(env.actor("sana"), env.doc_id, 1, "root")
    reply = comments.add(env.actor("priya"), env.doc_id, 2, "reply", parent_id=root.id)
    with pytest.raises(ValidationFailed):
        comments.add(env.actor("sana"), env.doc_id, 1, "nested", parent_id=reply.id)
    threads = comments.list_threads(env.actor("priya"), env.doc_id)
    assert len(threads) == 1 and [r.body for r in threads[0].replies] == ["reply"]


def test_team_cannot_comment_on_or_see_draft_versions(env, comments):
    with pytest.raises(ValidationFailed):
        comments.add(env.actor("sana"), env.doc_id, 2, "on the draft")
    draft_note = comments.add(env.actor("priya"), env.doc_id, 2, "owner note on draft")
    team_view = comments.list_threads(env.actor("sana"), env.doc_id)
    assert draft_note.id not in [t.root.id for t in team_view]
    assert draft_note.id in [t.root.id for t in comments.list_threads(env.actor("priya"), env.doc_id)]


def test_only_author_edits_and_deletes(env, comments):
    c = comments.add(env.actor("sana"), env.doc_id, 1, "mine")
    with pytest.raises(PermissionDenied):
        comments.edit(env.actor("dmitri"), c.id, "hijack")
    with pytest.raises(PermissionDenied):
        comments.edit(env.actor("priya"), c.id, "owner cannot edit others either")
    with pytest.raises(PermissionDenied):
        comments.delete(env.actor("priya"), c.id)
    edited = comments.edit(env.actor("sana"), c.id, "mine, edited")
    assert edited.body == "mine, edited" and edited.edited_at


def test_soft_delete_keeps_row_and_tombstones_thread_with_replies(env, comments):
    root = comments.add(env.actor("sana"), env.doc_id, 1, "root")
    comments.add(env.actor("priya"), env.doc_id, 2, "reply", parent_id=root.id)
    comments.delete(env.actor("sana"), root.id)
    (thread,) = comments.list_threads(env.actor("priya"), env.doc_id)
    assert thread.root.deleted and thread.root.body == "" and thread.replies[0].body == "reply"
    with env.db.read() as conn:
        assert conn.execute("select body from comments where id = ?", (root.id,)).fetchone()["body"] == "root"
        assert conn.execute("select count(*) n from audit_events where action='comment_deleted'").fetchone()["n"] == 1


def test_deleted_leaf_thread_disappears(env, comments):
    c = comments.add(env.actor("sana"), env.doc_id, 1, "oops")
    comments.delete(env.actor("sana"), c.id)
    assert comments.list_threads(env.actor("sana"), env.doc_id) == []


def test_resolve_and_reopen_only_for_resolvers(env, comments):
    c = comments.add(env.actor("sana"), env.doc_id, 1, "please fix")
    with pytest.raises(PermissionDenied):
        comments.set_resolved(env.actor("sana"), c.id, True)
    with pytest.raises(PermissionDenied):
        comments.set_resolved(env.actor("dmitri"), c.id, True)
    done = comments.set_resolved(env.actor("priya"), c.id, True)
    assert done.status == "resolved" and done.resolved_by
    assert [t.root.id for t in comments.list_threads(env.actor("sana"), env.doc_id, "resolved")] == [c.id]
    assert comments.list_threads(env.actor("sana"), env.doc_id, "open") == []
    assert comments.set_resolved(env.actor("priya"), c.id, False).status == "open"


def test_cannot_resolve_a_reply(env, comments):
    root = comments.add(env.actor("sana"), env.doc_id, 1, "root")
    reply = comments.add(env.actor("priya"), env.doc_id, 2, "reply", parent_id=root.id)
    with pytest.raises(ValidationFailed):
        comments.set_resolved(env.actor("priya"), reply.id, True)


def test_cross_tenant_and_unassigned_cannot_touch_comments(env, comments):
    c = comments.add(env.actor("sana"), env.doc_id, 1, "root")
    for who in ("gwen", "una"):
        with pytest.raises(NotFound):
            comments.list_threads(env.actor(who), env.doc_id)
        with pytest.raises(NotFound):
            comments.add(env.actor(who), env.doc_id, 1, "x")
        with pytest.raises(NotFound):
            comments.edit(env.actor(who), c.id, "x")
        with pytest.raises(NotFound):
            comments.set_resolved(env.actor(who), c.id, True)


def test_comment_survives_new_versions(env, comments):
    c = comments.add(env.actor("sana"), env.doc_id, 1, "about v1", anchor=ANCHOR)
    env.docs.publish(env.actor("priya"), env.doc_id, 2)
    env.docs.save_draft(env.actor("priya"), env.doc_id, 2, "<p>totally different</p>")
    env.docs.publish(env.actor("priya"), env.doc_id, 3)
    (t,) = comments.list_threads(env.actor("sana"), env.doc_id)
    assert t.root.id == c.id and t.root.version_number == 1


def test_validation(env, comments):
    with pytest.raises(ValidationFailed):
        comments.add(env.actor("sana"), env.doc_id, 1, "   ")
    with pytest.raises(ValidationFailed):
        comments.add(env.actor("sana"), env.doc_id, 1, "x", anchor={"quote": " "})


def test_threads_for_agent_needs_agent_use(env, comments):
    c = comments.add(env.actor("sana"), env.doc_id, 1, "incorporate me")
    with pytest.raises(PermissionDenied):
        comments.threads_for_agent(env.actor("sana"), env.doc_id, [c.id])
    assert [t.root.id for t in comments.threads_for_agent(env.actor("priya"), env.doc_id, [c.id])] == [c.id]


def test_owner_reply_written_on_the_draft_is_visible_to_the_team(env, comments):
    root = comments.add(env.actor("sana"), env.doc_id, 1, "question")
    comments.add(env.actor("priya"), env.doc_id, 2, "answer from the draft view", parent_id=root.id)
    (thread,) = comments.list_threads(env.actor("sana"), env.doc_id)
    assert [r.body for r in thread.replies] == ["answer from the draft view"]
