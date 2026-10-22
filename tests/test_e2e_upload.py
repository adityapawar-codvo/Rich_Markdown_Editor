"""Uploading existing files: they open as new drafts in the editor and are fully editable."""
from __future__ import annotations

import re

import pytest

from ctxeditor.importer import convert_upload
from ctxeditor.sanitizer import sanitize_html

from .browser import app_server, harness
from .test_e2e import EDITOR, db_versions, html, open_app, type_at_end, wait_html
from .test_importer import make_docx, make_pdf, make_pptx, make_xlsx

pytestmark = pytest.mark.browser

MARKDOWN = (b"# Imported notes\n\nSome *emphasis* and a list:\n\n- alpha\n- beta\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n"
            b"```mermaid\ngraph TD; A-->B\n```\n")


def upload(page, tmp_path, name: str, data: bytes) -> None:
    path = tmp_path / name
    path.write_bytes(data)
    page.get_by_role("button", name="Upload a file").click()
    page.wait_for_selector(".q-dialog .q-uploader")
    page.set_input_files(".q-dialog .q-uploader input[type=file]", str(path))


def open_in_editor(page) -> None:
    page.get_by_role("button", name="Open in editor").click()


def test_uploaded_word_file_opens_editable_and_can_be_edited_and_saved(chromium, tmp_path):
    with app_server() as (url, db):
        page = open_app(chromium, url)
        upload(page, tmp_path, "Project_brief.docx", make_docx())
        page.wait_for_selector("text=Ready: Project_brief.docx")
        assert page.locator(".q-dialog input").first.input_value() == "Project brief"
        assert "1 image was not imported" in page.locator(".q-dialog").inner_text()
        open_in_editor(page)
        page.wait_for_selector(".ws-title:has-text('Project brief')")
        wait_html(page, "Project brief")
        out = html(page)
        assert "<h1>Project brief</h1>" in out and "<strong>bold</strong>" in out and "<table>" in out
        # fully editable: the toolbar is there and typing works
        assert page.locator(EDITOR).get_attribute("contenteditable") == "true"
        assert page.locator(".cx-toolbar").first.is_visible()
        type_at_end(page, " EDITED-AFTER-IMPORT")
        page.get_by_role("button", name=re.compile("^Save as new version")).click()
        page.wait_for_selector("text=Saved as version 2")
        page.reload()
        page.locator(".ws-doc-item:has-text('Project brief')").click()
        wait_html(page, "EDITED-AFTER-IMPORT")
        assert "Draft" in page.locator(".ws-doc-item:has-text('Project brief')").inner_text()
        page.context.close()


def test_uploaded_file_is_a_private_draft_until_published(chromium, tmp_path):
    with app_server() as (url, db):
        owner = open_app(chromium, url)
        upload(owner, tmp_path, "secret.md", MARKDOWN)
        owner.wait_for_selector("text=Ready: secret.md")
        open_in_editor(owner)
        owner.wait_for_selector(".ws-title:has-text('secret')")
        team = open_app(chromium, url, "Sana Okafor")
        team.wait_for_selector(".ws-doc-item")
        assert team.locator(".ws-doc-item:has-text('secret')").count() == 0
        owner.context.close()
        team.context.close()


@pytest.mark.parametrize("name,data,needle", [
    ("notes.md", MARKDOWN, "Imported notes"),
    ("budget.xlsx", None, "Licences"),
    ("deck.pptx", None, "Roadmap"),
    ("report.pdf", None, "Annual Report"),
    ("data.csv", b"id,name\n1,Ada\n2,Grace\n", "Grace"),
    ("page.html", b"<h1>Web page</h1><p>Hello <b>there</b></p><script>x()</script>", "Web page"),
    ("plain.txt", b"Just some text\n\nSecond paragraph", "Second paragraph"),
])
def test_every_supported_type_uploads_and_opens(chromium, tmp_path, name, data, needle):
    data = data if data is not None else {"budget.xlsx": make_xlsx, "deck.pptx": make_pptx, "report.pdf": make_pdf}[name]()
    with app_server() as (url, db):
        page = open_app(chromium, url)
        upload(page, tmp_path, name, data)
        page.wait_for_selector(f"text=Ready: {name}")
        open_in_editor(page)
        stem = name.rsplit(".", 1)[0].replace("_", " ")
        page.wait_for_selector(f".ws-title:has-text('{stem}')")
        wait_html(page, needle)
        assert page.locator(EDITOR).get_attribute("contenteditable") == "true"
        assert "<script" not in html(page)
        page.context.close()


def test_markdown_mermaid_fence_becomes_a_live_diagram(chromium, tmp_path):
    with app_server() as (url, db):
        page = open_app(chromium, url)
        upload(page, tmp_path, "diagram.md", MARKDOWN)
        page.wait_for_selector("text=Ready: diagram.md")
        open_in_editor(page)
        page.wait_for_selector(f"{EDITOR} .cx-mermaid svg", timeout=30000)
        page.context.close()


@pytest.mark.parametrize("name,data,message", [
    ("old.doc", b"x" * 10, "old format"),
    ("tool.exe", b"MZ" * 10, "Upload a Word"),
    ("fake.docx", b"not really a docx", "not a real .docx"),
    ("scan.pdf", None, "no text layer"),
])
def test_unsupported_and_bad_files_show_a_clear_error_and_create_nothing(chromium, tmp_path, name, data, message):
    data = data if data is not None else make_pdf(scanned=True)
    with app_server() as (url, db):
        page = open_app(chromium, url)
        before = page.locator(".ws-doc-item").count()
        upload(page, tmp_path, name, data)
        page.wait_for_selector(f".q-dialog .text-negative:has-text('{message}')", timeout=20000)
        assert page.get_by_role("button", name="Open in editor").is_disabled()
        page.get_by_role("button", name="Cancel").click()
        assert page.locator(".ws-doc-item").count() == before
        page.context.close()


def test_oversized_file_is_rejected(chromium, tmp_path):
    with app_server() as (url, db):
        page = open_app(chromium, url)
        upload(page, tmp_path, "huge.txt", b"a" * (10 * 1024 * 1024 + 10))
        page.wait_for_selector(".q-dialog .text-negative:has-text('too large')", timeout=20000)
        page.context.close()


def test_upload_is_not_offered_to_team_members(chromium):
    with app_server() as (url, db):
        for persona in ("Dmitri Volkov", "Sana Okafor", "Erin Walsh"):
            page = open_app(chromium, url, persona)
            assert page.get_by_role("button", name="Upload a file").count() == 0
            assert page.get_by_role("button", name="New document").count() == 0
            page.context.close()


def test_upload_can_be_cancelled_without_creating_a_document(chromium, tmp_path):
    with app_server() as (url, db):
        page = open_app(chromium, url)
        before = page.locator(".ws-doc-item").count()
        upload(page, tmp_path, "cancel.txt", b"never saved")
        page.wait_for_selector("text=Ready: cancel.txt")
        page.get_by_role("button", name="Cancel").click()
        page.wait_for_selector(".q-dialog", state="detached")
        assert page.locator(".ws-doc-item").count() == before
        assert db_versions(db) == [1, 2]
        page.context.close()


def test_title_and_type_can_be_changed_before_opening(chromium, tmp_path):
    with app_server() as (url, db):
        page = open_app(chromium, url)
        upload(page, tmp_path, "draft_v3.txt", b"hello")
        page.wait_for_selector("text=Ready: draft_v3.txt")
        title = page.locator(".q-dialog input").first
        title.click()
        page.keyboard.press("ControlOrMeta+a")
        page.keyboard.type("Vendor assessment")
        open_in_editor(page)
        page.wait_for_selector(".ws-title:has-text('Vendor assessment')")
        page.context.close()


@pytest.mark.parametrize("name", ["docx", "xlsx", "pptx", "pdf", "md"])
def test_imported_content_is_stable_through_the_editor(chromium, name):
    """What the editor makes of an imported document is still allowlisted HTML with the same text."""
    builders = {"docx": ("a.docx", make_docx), "xlsx": ("a.xlsx", make_xlsx), "pptx": ("a.pptx", make_pptx),
                "pdf": ("a.pdf", make_pdf), "md": ("a.md", lambda: MARKDOWN)}
    filename, build = builders[name]
    imported = convert_upload(filename, build())
    with harness(imported.html) as url:
        page = chromium.new_page()
        page.goto(url)
        page.wait_for_function("document.querySelector('.cx-root') && document.querySelector('.cx-root').__cxController")
        out = page.evaluate("document.querySelector('.cx-root').__cxController.getHtml()")
        assert sanitize_html(out) == sanitize_html(sanitize_html(out))
        strip = lambda h: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h)).strip()  # noqa: E731
        assert strip(out).replace("&amp;", "&") == strip(imported.html).replace("&amp;", "&")
        page.close()
