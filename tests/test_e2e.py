"""End-to-end flows in a real browser against the real app: edit, save, version, stale save, publish, read-only
team view, comments, history, export, diagrams, charts and the assistant."""
from __future__ import annotations

import re
import sqlite3

import pytest

from .browser import app_server

pytestmark = pytest.mark.browser

EDITOR = ".cx-canvas .ProseMirror"


def open_app(chromium, url, persona: str | None = None, viewport=(1500, 950)):
    context = chromium.new_context(viewport={"width": viewport[0], "height": viewport[1]}, accept_downloads=True)
    page = context.new_page()
    page.goto(url)
    page.wait_for_selector(EDITOR, timeout=20000)
    if persona:
        switch(page, persona)
    page.wait_for_selector("[data-testid='doc-title'], .ws-title", timeout=20000)
    return page


def switch(page, name: str) -> None:
    page.locator(".q-select").first.click()
    page.get_by_role("option", name=re.compile(name)).first.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_selector(EDITOR, timeout=20000)
    page.wait_for_selector(".ws-title", timeout=20000)


def html(page) -> str:
    return page.evaluate("document.querySelector('.cx-root').__cxController.getHtml()")


def wait_html(page, needle: str, present: bool = True) -> None:
    js = f"document.querySelector('.cx-root').__cxController.getHtml().includes({needle!r})"
    page.wait_for_function(js if present else f"!({js})", timeout=15000)


def version_text(page) -> str:
    return page.locator(".ws-title").first.locator("xpath=../..").locator(".ws-badge").last.inner_text()


def db_versions(db: str) -> list[int]:
    conn = sqlite3.connect(db)
    try:
        return [r[0] for r in conn.execute("select version_number from document_versions order by version_number")]
    finally:
        conn.close()


def type_at_end(page, text: str) -> None:
    page.click(EDITOR)
    page.keyboard.press("Control+End")
    page.keyboard.type(text)


def test_owner_edits_saves_and_version_increments(chromium):
    with app_server() as (url, db):
        page = open_app(chromium, url)  # default persona is the product owner
        assert page.locator("[aria-label='Toolbar'], .cx-toolbar").first.is_visible()
        assert "v2" in page.locator(".ws-title").locator("xpath=../..").inner_text()
        type_at_end(page, " New sentence.")
        page.wait_for_selector(".ws-dirty", state="visible")
        page.get_by_role("button", name=re.compile("Save as new version")).click()
        page.wait_for_selector("text=Saved as version 3")
        page.wait_for_selector(".ws-dirty", state="hidden")
        assert "v3" in page.locator(".ws-title").locator("xpath=../..").inner_text()
        assert db_versions(db)[-1] == 3
        page.reload()
        wait_html(page, "New sentence.")
        page.context.close()


def test_keyboard_save_shortcut(chromium):
    with app_server() as (url, db):
        page = open_app(chromium, url)
        type_at_end(page, " via shortcut")
        page.keyboard.press("ControlOrMeta+s")
        page.wait_for_selector("text=Saved as version 3")
        page.context.close()


def test_stale_save_is_rejected_with_clear_message(chromium):
    with app_server() as (url, db):
        a = open_app(chromium, url)
        b = open_app(chromium, url)
        type_at_end(a, " from tab A")
        a.get_by_role("button", name=re.compile("Save as new version")).click()
        a.wait_for_selector("text=Saved as version 3")
        type_at_end(b, " from tab B")
        b.get_by_role("button", name=re.compile("Save as new version")).click()
        b.wait_for_selector("[data-testid='stale-banner'], .ws-banner.error")
        assert "changed since you opened it" in b.locator(".ws-banner.error").inner_text()
        assert "from tab B" in html(b)  # the user's text stays
        assert db_versions(db)[-1] == 3
        b.get_by_role("button", name="Reload latest version").click()
        wait_html(b, "from tab A")
        a.context.close()
        b.context.close()


def test_team_member_sees_published_only_read_only_and_cannot_edit(chromium):
    with app_server() as (url, db):
        page = open_app(chromium, url, "Sana Okafor")
        assert "v1" in page.locator(".ws-title").locator("xpath=../..").inner_text()
        wait_html(page, "Goals")
        assert "Open questions" not in html(page)
        assert page.locator(".cx-toolbar").first.is_hidden()
        assert page.locator(EDITOR).get_attribute("contenteditable") == "false"
        assert page.get_by_role("button", name="Publish this version").count() == 0
        page.context.close()


def test_publish_flow_team_sees_new_version_and_later_drafts_stay_hidden(chromium):
    with app_server() as (url, db):
        owner = open_app(chromium, url)
        owner.get_by_role("button", name="Publish this version").click()
        owner.locator(".q-dialog textarea").first.click()
        owner.keyboard.type("Adds open questions")
        owner.get_by_role("button", name="Publish", exact=True).click()
        owner.wait_for_selector("text=Version 2 published")
        team = open_app(chromium, url, "Dmitri Volkov")
        wait_html(team, "Open questions")
        type_at_end(owner, " Third draft.")
        owner.get_by_role("button", name=re.compile("Save as new version")).click()
        owner.wait_for_selector("text=Saved as version 3")
        team.reload()
        wait_html(team, "Open questions")
        assert "Third draft" not in html(team)
        owner.context.close()
        team.context.close()
