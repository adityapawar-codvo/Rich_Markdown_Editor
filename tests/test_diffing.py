from __future__ import annotations

from ctxeditor.diffing import accept_all, apply_decisions, diff_html, hunks, split_blocks
from ctxeditor.sample_content import SAMPLE_HTML, SAMPLE_HTML_V2
from ctxeditor.sanitizer import sanitize_html

BASE = "<h1>Title</h1><p>The quick brown fox jumps over the lazy dog.</p><p>Second paragraph.</p>"


def test_identical_documents_have_no_hunks():
    segments = diff_html(BASE, BASE)
    assert hunks(segments) == [] and accept_all(segments) == BASE


def test_added_block():
    new = BASE + "<p>A brand new closing thought.</p>"
    hs = hunks(diff_html(BASE, new))
    assert [(h.kind, h.new_html) for h in hs] == [("added", "<p>A brand new closing thought.</p>")]


def test_removed_block():
    new = "<h1>Title</h1><p>Second paragraph.</p>"
    hs = hunks(diff_html(BASE, new))
    assert [h.kind for h in hs] == [("removed")]


def test_modified_block_has_inline_markup():
    new = BASE.replace("quick brown", "slow red")
    (h,) = hunks(diff_html(BASE, new))
    assert h.kind == "modified" and "<del>" in h.inline_html and "<ins>" in h.inline_html
    assert "slow" in h.inline_html and "quick" in h.inline_html
    assert h.inline_html.startswith("<p>") and h.inline_html.endswith("</p>")


def test_accept_all_and_reject_all_are_exact():
    new = "<h1>Title</h1><p>The slow red fox jumps over the lazy dog.</p><p>Inserted.</p>"
    segments = diff_html(BASE, new)
    assert accept_all(segments) == new
    assert apply_decisions(segments, set()) == BASE


def test_partial_accept():
    new = "<h1>Title</h1><p>The slow red fox jumps over the lazy dog.</p><p>Second paragraph.</p><p>Extra.</p>"
    segments = diff_html(BASE, new)
    ids = [h.hunk_id for h in hunks(segments)]
    assert len(ids) == 2
    only_extra = apply_decisions(segments, {ids[1]})
    assert "quick brown" in only_extra and "Extra." in only_extra and "slow red" not in only_extra


def test_table_change_is_a_whole_block_hunk():
    old = "<table><tbody><tr><td><p>a</p></td></tr></tbody></table>"
    new = "<table><tbody><tr><td><p>b</p></td></tr></tbody></table>"
    (h,) = hunks(diff_html(old, new))
    assert h.kind in ("modified", "removed", "added") and h.inline_html is None


def test_sample_versions_diff_adds_open_questions_and_chart():
    segments = diff_html(SAMPLE_HTML, SAMPLE_HTML_V2)
    kinds = [h.kind for h in hunks(segments)]
    assert kinds and set(kinds) == {"added"}
    assert sanitize_html(accept_all(segments)) == SAMPLE_HTML_V2
    assert apply_decisions(segments, set()) == "".join(split_blocks(SAMPLE_HTML))


def test_mermaid_block_preserved_when_rejecting():
    base = '<div data-type="mermaid">graph TD; A--&gt;B</div><p>x</p>'
    new = '<div data-type="mermaid">graph TD; A--&gt;C</div><p>x</p>'
    segments = diff_html(base, new)
    assert apply_decisions(segments, set()) == base


def test_empty_inputs():
    assert diff_html("", "") == []
    assert accept_all(diff_html("", "<p>a</p>")) == "<p>a</p>"
    assert apply_decisions(diff_html("<p>a</p>", ""), set()) == "<p>a</p>"
