"""More end-to-end flows: comments, history and compare, diagrams, charts, export, the assistant, themes, tablet."""
from __future__ import annotations

import io
import re

import pytest
from pypdf import PdfReader

from .browser import app_server
from .test_e2e import EDITOR, db_versions, html, open_app, switch, type_at_end, wait_html

pytestmark = pytest.mark.browser


def btn(page, name: str):
    return page.get_by_role("button", name=re.compile(rf"^{re.escape(name)}"))


def type_into(locator, text: str) -> None:
    """Quasar's autogrow textareas drop the value that Playwright's fill() sets; real typing works."""
    locator.click()
    locator.page.keyboard.type(text)


def select_text(page, needle: str) -> None:
    """Select the first occurrence of `needle` in the document, exactly as a user dragging over it would."""
    found = page.evaluate("""(needle) => {
        const e = document.querySelector('.cx-root').__cxController.editor;
        let range = null;
        e.state.doc.descendants((node, pos) => {
          if (range || !node.isText) return;
          const at = node.text.indexOf(needle);
          if (at >= 0) range = [pos + at, pos + at + needle.length];
        });
        if (!range) return false;
        e.view.focus();
        e.commands.setTextSelection({ from: range[0], to: range[1] });
        return true; }""", needle)
    assert found, needle


# ----------------------------------------------------------------------------------------------- comments

def test_team_member_annotates_text_and_owner_resolves(chromium):
    with app_server() as (url, db):
        sana = open_app(chromium, url, "Sana Okafor")
        wait_html(sana, "Goals")
        select_text(sana, "Goals")
        sana.wait_for_selector(".cx-bubble", state="visible")
        btn(sana, "Comment on selection").click()
        type_into(sana.locator(".q-tab-panel textarea").first, "Are goals measurable?")
        btn(sana, "Post comment").click()
        sana.wait_for_selector("text=Comment added")
        sana.wait_for_selector(f"{EDITOR} .cx-comment")
        card = sana.locator("[id^='c-']").first
        assert "Are goals measurable?" in card.inner_text()
        assert "QA" in card.inner_text() and "v1" in card.inner_text() and "Goals" in card.inner_text()
        sana.reload()
        sana.wait_for_selector(f"{EDITOR} .cx-comment")  # the highlight is rebuilt from the stored anchor
        assert sana.locator(f"{EDITOR} .cx-comment").first.inner_text() == "Goals"
        # a team member cannot resolve
        assert sana.get_by_role("button", name="Resolve", exact=True).count() == 0
        # clicking the highlight opens the thread
        sana.locator(f"{EDITOR} .cx-comment").first.click()
        owner = open_app(chromium, url)
        owner.wait_for_selector(f"{EDITOR} .cx-comment")
        owner.get_by_role("button", name="Resolve", exact=True).click()
        owner.wait_for_selector("text=Comment resolved")
        owner.wait_for_selector(f"{EDITOR} .cx-comment-resolved")
        owner.get_by_text("Resolved", exact=True).first.click()  # the filter
        assert "Are goals measurable?" in owner.locator("[id^='c-']").first.inner_text()
        owner.get_by_role("button", name="Reopen", exact=True).click()
        owner.wait_for_selector("text=Comment reopened")
        sana.context.close()
        owner.context.close()


def test_general_comment_reply_edit_delete_and_filters(chromium):
    with app_server() as (url, db):
        arjun = open_app(chromium, url, "Arjun Mehta")
        type_into(arjun.locator(".q-tab-panel textarea").first, "General: scope is unclear")
        btn(arjun, "Post general comment").click()
        arjun.wait_for_selector("text=Comment added")
        card = arjun.locator("[id^='c-']").first
        assert "Architect" in card.inner_text() and "General: scope is unclear" in card.inner_text()
        btn(arjun, "Edit comment").first.click()
        type_into(arjun.locator(".ws-comment textarea").first, "General: scope is still unclear")
        btn(arjun, "Save comment").click()
        arjun.wait_for_selector("text=scope is still unclear")
        assert "edited" in arjun.locator("[id^='c-']").first.inner_text()
        owner = open_app(chromium, url)
        btn(owner, "Reply").first.click()
        type_into(owner.locator(".ws-comment textarea").first, "Will clarify")
        btn(owner, "Post reply").click()
        owner.wait_for_selector("text=Will clarify")
        owner.get_by_text("Open", exact=True).first.click()
        assert owner.locator("[id^='c-']").count() == 1
        arjun.reload()
        arjun.wait_for_selector("[id^='c-']")
        btn(arjun, "Delete comment").first.click()
        arjun.get_by_role("button", name="Delete", exact=True).click()
        arjun.wait_for_selector("text=This comment was deleted")
        arjun.context.close()
        owner.context.close()


def test_removed_text_marks_comment_not_present(chromium):
    with app_server() as (url, db):
        sana = open_app(chromium, url, "Sana Okafor")
        wait_html(sana, "Goals")
        select_text(sana, "Goals")
        btn(sana, "Comment on selection").click()
        type_into(sana.locator(".q-tab-panel textarea").first, "About goals")
        btn(sana, "Post comment").click()
        sana.wait_for_selector("text=Comment added")
        owner = open_app(chromium, url)
        wait_html(owner, "Goals")
        owner.locator(f"{EDITOR} h2").first.click()
        owner.keyboard.press("Home")
        for _ in range(5):
            owner.keyboard.press("Shift+ArrowRight")
        owner.keyboard.type("Aims")
        owner.keyboard.press("ControlOrMeta+s")
        owner.wait_for_selector("text=Saved as version 3")
        owner.wait_for_selector("text=text no longer present")
        assert "About goals" in owner.locator("[id^='c-']").first.inner_text()
        sana.context.close()
        owner.context.close()


# ----------------------------------------------------------------------------------------------- history

def test_history_compare_and_restore(chromium):
    with app_server() as (url, db):
        owner = open_app(chromium, url)
        owner.get_by_role("tab", name="History").click()
        owner.wait_for_selector("text=Version 1")
        btn(owner, "Compare with latest").click()
        owner.wait_for_selector(".cx-hunk-added")
        assert "Comparing version 1 with version 2" in owner.locator(".ws-banner").first.inner_text()
        assert owner.locator(".cx-hunk-accept").count() == 0  # compare is view-only
        btn(owner, "Close comparison").click()
        owner.wait_for_selector(".cx-hunk", state="detached")
        btn(owner, "Restore as new draft").click()
        owner.get_by_role("button", name="Restore", exact=True).click()
        owner.wait_for_selector("text=as version 3 (draft)")
        assert "Open questions" not in html(owner)
        assert db_versions(db) == [1, 2, 3]
        btn(owner, "View this version").nth(2).click()  # oldest entry in the list
        owner.wait_for_selector("text=Viewing version 1 (read-only)")
        assert owner.locator(EDITOR).get_attribute("contenteditable") == "false"
        btn(owner, "Back to the latest version").click()
        owner.wait_for_selector("text=Viewing version", state="detached")
        owner.context.close()


def test_owner_can_view_what_the_team_sees(chromium):
    with app_server() as (url, db):
        owner = open_app(chromium, url)
        btn(owner, "View what the team sees").click()
        owner.wait_for_selector("text=This is the version your team sees")
        wait_html(owner, "Goals")
        assert "Open questions" not in html(owner)
        owner.context.close()


# ----------------------------------------------------------------------------------------------- diagrams and charts

def test_mermaid_dialog_live_preview_error_and_save(chromium):
    with app_server() as (url, db):
        owner = open_app(chromium, url)
        owner.wait_for_selector(f"{EDITOR} .cx-mermaid svg", timeout=30000)  # rendered live, not just code
        owner.locator(f"{EDITOR} .cx-mermaid").click()
        owner.wait_for_selector(".cx-modal .cx-code-input")
        owner.wait_for_selector(".cx-modal .cx-preview svg")
        area = owner.locator(".cx-modal .cx-code-input")
        area.fill("flowchart TD\n  A[Alpha] --> B[Beta]")
        owner.wait_for_selector(".cx-modal .cx-preview svg:has-text('Alpha')", timeout=15000)
        assert "valid" in owner.locator(".cx-status").inner_text().lower()
        area.fill("flowchart TD\n  A[Alpha -->")
        owner.wait_for_selector(".cx-status-error", timeout=15000)
        assert owner.locator(".cx-modal .cx-preview svg:has-text('Alpha')").count() == 1  # last good preview stays
        area.fill("flowchart LR\n  X[Start] --> Y[Done]")
        owner.wait_for_selector(".cx-status-ok", timeout=15000)
        owner.get_by_role("button", name="Save diagram").click()
        owner.wait_for_selector(".cx-modal", state="detached")
        assert "X[Start] --&gt; Y[Done]" in html(owner)
        owner.wait_for_selector(f"{EDITOR} .cx-mermaid svg:has-text('Start')", timeout=15000)
        owner.context.close()


def test_invalid_mermaid_shows_error_card_without_crashing(chromium):
    with app_server() as (url, db):
        owner = open_app(chromium, url)
        owner.locator(f"{EDITOR} .cx-mermaid").click()
        owner.locator(".cx-modal .cx-code-input").fill("this is ((( not mermaid")
        owner.wait_for_selector(".cx-status-error", timeout=15000)
        owner.get_by_role("button", name="Save diagram").click()
        owner.wait_for_selector(f"{EDITOR} .cx-mermaid.cx-has-error", timeout=15000)
        assert owner.locator(EDITOR).is_visible()
        owner.context.close()


def test_chart_dialog_edits_values_and_type(chromium):
    with app_server() as (url, db):
        owner = open_app(chromium, url)
        owner.wait_for_selector(f"{EDITOR} .cx-chart canvas", timeout=30000)
        owner.locator(f"{EDITOR} .cx-chart").first.click()
        owner.wait_for_selector(".cx-modal .cx-data-table")
        owner.locator(".cx-modal .cx-num").first.fill("999")
        owner.locator(".cx-modal select").select_option("line")
        owner.get_by_role("button", name="Add row").click()
        owner.get_by_role("button", name="Save chart").click()
        owner.wait_for_selector(".cx-modal", state="detached")
        out = html(owner)
        assert "999" in out and "&quot;type&quot;:&quot;line&quot;" in out and "Item 5" in out
        owner.locator(f"{EDITOR} .cx-chart").first.click()
        owner.locator(".cx-modal .cx-num").first.fill("abc")
        owner.get_by_role("button", name="Save chart").click()
        assert "number" in owner.locator(".cx-status-error").inner_text().lower()
        owner.context.close()


# ----------------------------------------------------------------------------------------------- export

def test_pdf_export_download_matches_document(chromium):
    with app_server() as (url, db):
        team = open_app(chromium, url, "Erin Walsh")
        wait_html(team, "Goals")
        btn(team, "Export").click()
        with team.expect_download() as info:
            team.get_by_text("PDF (.pdf)").click()
        download = info.value
        assert download.suggested_filename == "context-editor-showcase-v1.pdf"
        text = "\n".join(p.extract_text() for p in PdfReader(download.path()).pages)
        assert "Goals" in text and "Page 1 of" in text and "DRAFT" not in text and "Open questions" not in text
        team.context.close()


def test_owner_draft_export_is_marked_draft(chromium):
    with app_server() as (url, db):
        owner = open_app(chromium, url)
        wait_html(owner, "Open questions")
        btn(owner, "Export").click()
        with owner.expect_download() as info:
            owner.get_by_text("PDF (.pdf)").click()
        assert info.value.suggested_filename.endswith("-v2-DRAFT.pdf")
        owner.context.close()


# ----------------------------------------------------------------------------------------------- assistant

def test_assistant_proposes_diff_and_accept_creates_draft_version(chromium):
    with app_server() as (url, db):
        owner = open_app(chromium, url)
        wait_html(owner, "Goals")
        owner.get_by_role("tab", name="Assistant").click()
        type_into(owner.locator(".q-tab-panel textarea").last, "Add a closing note and retitle")
        btn(owner, "Send to the assistant").click()
        owner.wait_for_selector(".cx-hunk", timeout=20000)
        assert owner.locator(".cx-hunk-added").count() >= 1 and owner.locator(".cx-hunk-modified").count() == 1
        assert db_versions(db) == [1, 2]  # nothing is saved until the owner accepts
        btn(owner, "Accept all changes").click()
        btn(owner, "Apply accepted changes").click()
        owner.wait_for_selector("text=Saved as version 3", timeout=15000)
        owner.wait_for_selector(".cx-hunk", state="detached")
        wait_html(owner, "Added by the assistant.")
        assert "Revised: " in html(owner)
        assert db_versions(db) == [1, 2, 3]
        conn = __import__("sqlite3").connect(db)
        assert conn.execute("select source from document_versions where version_number = 3").fetchone()[0] == "agent"
        assert conn.execute("select result_status from agent_requests").fetchone()[0] == "accepted"
        conn.close()
        owner.context.close()


def test_assistant_reject_leaves_document_unchanged(chromium):
    with app_server() as (url, db):
        owner = open_app(chromium, url)
        wait_html(owner, "Goals")
        owner.get_by_role("tab", name="Assistant").click()
        type_into(owner.locator(".q-tab-panel textarea").last, "Change things")
        btn(owner, "Send to the assistant").click()
        owner.wait_for_selector(".cx-hunk", timeout=20000)
        btn(owner, "Reject all changes").click()
        btn(owner, "Apply accepted changes").click()
        owner.wait_for_selector("text=No changes were applied")
        assert db_versions(db) == [1, 2]
        assert "Added by the assistant" not in html(owner)
        owner.context.close()


def test_assistant_partial_accept(chromium):
    with app_server() as (url, db):
        owner = open_app(chromium, url)
        wait_html(owner, "Goals")
        owner.get_by_role("tab", name="Assistant").click()
        type_into(owner.locator(".q-tab-panel textarea").last, "Edit")
        btn(owner, "Send to the assistant").click()
        owner.wait_for_selector(".cx-hunk", timeout=20000)
        owner.locator(".cx-hunk-added .cx-hunk-accept").first.click()
        btn(owner, "Apply accepted changes").click()
        owner.wait_for_selector("text=Saved as version 3", timeout=15000)
        wait_html(owner, "Added by the assistant.")
        assert "Revised: " not in html(owner)  # the modified hunk was not accepted
        owner.context.close()


def test_assistant_unavailable_to_team(chromium):
    with app_server() as (url, db):
        team = open_app(chromium, url, "Dmitri Volkov")
        team.get_by_role("tab", name="Assistant").click()
        team.wait_for_selector("text=available to the product owner")
        assert team.locator("[aria-label='Send to the assistant']").count() == 0
        team.context.close()


# ----------------------------------------------------------------------------------------------- look and feel

def test_dark_mode_toggle(chromium):
    with app_server() as (url, db):
        page = open_app(chromium, url)
        btn(page, "Toggle dark mode").click()
        page.wait_for_selector(".cx-root.cx-dark")
        assert page.evaluate("getComputedStyle(document.querySelector('.cx-root')).backgroundColor") != "rgb(255, 255, 255)"
        page.reload()
        page.wait_for_selector(".cx-root.cx-dark")  # remembered
        page.context.close()


def test_tablet_width_has_no_horizontal_scroll_and_drawers_collapse(chromium):
    with app_server() as (url, db):
        page = open_app(chromium, url, viewport=(820, 1000))
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        assert page.locator(EDITOR).is_visible()
        btn(page, "Toggle documents").click()
        page.wait_for_selector(".q-drawer--left .ws-doc-item")
        page.context.close()


def test_fonts_are_self_hosted(chromium):
    with app_server() as (url, db):
        page = open_app(chromium, url)
        requests = []
        page.on("request", lambda r: requests.append(r.url))
        page.reload()
        page.wait_for_selector(EDITOR)
        page.wait_for_timeout(1500)
        assert not [r for r in requests if "googleapis" in r or "gstatic" in r or "cdn" in r]
        assert page.evaluate("document.fonts.check('16px Inter')") and page.evaluate("document.fonts.check('16px \"Source Serif 4\"')")
        page.context.close()


# ----------------------------------------------------------------------------------------------- unsaved edits are kept

def test_unsaved_edits_survive_looking_at_what_the_team_sees(chromium):
    with app_server() as (url, db):
        owner = open_app(chromium, url)
        wait_html(owner, "Open questions")
        type_at_end(owner, " UNSAVED-EDIT")
        owner.wait_for_selector(".ws-dirty", state="visible")
        btn(owner, "View what the team sees").click()
        owner.wait_for_selector("text=This is the version your team sees")
        wait_html(owner, "UNSAVED-EDIT", present=False)  # the team's version has none of it
        assert owner.locator("[data-testid='kept-banner'], .ws-banner:has-text('unsaved edits are kept')").count() == 1
        assert owner.locator(".ws-dirty").is_visible()  # the indicator says edits are being held
        btn(owner, "View what the team sees").click()  # the eye again: come back
        wait_html(owner, "UNSAVED-EDIT")
        owner.wait_for_selector("text=This is the version your team sees", state="detached")
        owner.wait_for_selector(".ws-dirty", state="visible")
        owner.get_by_role("button", name=re.compile("^Save as new version")).click()
        owner.wait_for_selector("text=Saved as version 3")
        assert db_versions(db) == [1, 2, 3]
        owner.reload()
        wait_html(owner, "UNSAVED-EDIT")
        owner.context.close()


def test_unsaved_edits_survive_the_back_button_and_history_peek(chromium):
    with app_server() as (url, db):
        owner = open_app(chromium, url)
        wait_html(owner, "Open questions")
        type_at_end(owner, " KEEP-ME")
        owner.wait_for_selector(".ws-dirty", state="visible")
        owner.get_by_role("tab", name="History").click()
        owner.wait_for_selector("text=Version 1")
        btn(owner, "View this version").nth(1).click()
        owner.wait_for_selector("text=Viewing version 1 (read-only)")
        wait_html(owner, "KEEP-ME", present=False)
        btn(owner, "Back to the latest version").click()
        wait_html(owner, "KEEP-ME")
        assert owner.locator(EDITOR).get_attribute("contenteditable") == "true"
        owner.context.close()


def test_clicking_the_open_document_does_not_reload_over_edits(chromium):
    with app_server() as (url, db):
        owner = open_app(chromium, url)
        wait_html(owner, "Open questions")
        type_at_end(owner, " STILL-HERE")
        owner.wait_for_selector(".ws-dirty", state="visible")
        owner.locator(".ws-doc-item").first.click()
        owner.wait_for_timeout(800)
        assert "STILL-HERE" in html(owner)
        owner.context.close()


def test_switching_documents_with_kept_edits_asks_first(chromium):
    with app_server() as (url, db):
        owner = open_app(chromium, url)
        wait_html(owner, "Open questions")
        owner.get_by_role("button", name="New document").click()
        owner.locator(".q-dialog input").first.fill("Second doc")
        owner.get_by_role("button", name="Create").click()
        owner.wait_for_selector(".ws-title:has-text('Second doc')")
        owner.locator(".ws-doc-item:has-text('Context editor showcase')").click()
        wait_html(owner, "Open questions")
        type_at_end(owner, " PRECIOUS")
        owner.wait_for_selector(".ws-dirty", state="visible")
        btn(owner, "View what the team sees").click()  # edits are now only held aside
        owner.wait_for_selector("text=This is the version your team sees")
        owner.locator(".ws-doc-item:has-text('Second doc')").click()
        owner.wait_for_selector("text=Discard unsaved changes?")
        owner.get_by_role("button", name="Cancel").click()
        owner.wait_for_selector(".ws-title:has-text('Context editor showcase')")
        btn(owner, "View what the team sees").click()
        wait_html(owner, "PRECIOUS")
        owner.context.close()


def test_kept_edits_made_stale_by_another_save_are_not_saved_over_it(chromium):
    with app_server() as (url, db):
        a = open_app(chromium, url)
        b = open_app(chromium, url)
        wait_html(a, "Open questions")
        wait_html(b, "Open questions")
        type_at_end(a, " MY-EDIT")
        a.wait_for_selector(".ws-dirty", state="visible")
        btn(a, "View what the team sees").click()
        a.wait_for_selector("text=This is the version your team sees")
        type_at_end(b, " THEIR-EDIT")
        b.get_by_role("button", name=re.compile("^Save as new version")).click()
        b.wait_for_selector("text=Saved as version 3")
        btn(a, "View what the team sees").click()  # come back after the other save
        wait_html(a, "MY-EDIT")
        a.wait_for_selector(".ws-banner.error")
        a.get_by_role("button", name=re.compile("^Save as new version")).click()
        a.wait_for_selector("text=changed since you opened it")
        assert db_versions(db) == [1, 2, 3]  # nothing was overwritten
        assert "MY-EDIT" in html(a)  # and the owner's text is still there to copy
        a.context.close()
        b.context.close()
