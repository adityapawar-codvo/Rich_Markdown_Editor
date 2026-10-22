"""The contract between the editor schema (JavaScript) and the sanitizer allowlist (Python): every node and mark the
editor can emit must survive the sanitizer unchanged, and the sample document must survive the editor unchanged."""
from __future__ import annotations

import pytest

from ctxeditor.sample_content import SAMPLE_HTML, SAMPLE_HTML_V2
from ctxeditor.sanitizer import sanitize_html

from .browser import harness

pytestmark = pytest.mark.browser


def editor_html(page) -> str:
    return page.evaluate("document.querySelector('.cx-root').__cxController.getHtml()")


@pytest.mark.parametrize("html", [SAMPLE_HTML, SAMPLE_HTML_V2], ids=["v1", "v2"])
def test_sample_survives_editor_and_sanitizer_unchanged(chromium, html):
    with harness(html) as url:
        page = chromium.new_page()
        page.goto(url)
        page.wait_for_selector(".cx-canvas .ProseMirror")
        page.wait_for_function("document.querySelector('.cx-root').__cxController !== undefined")
        out = editor_html(page)
        assert out == html, "editor serialization differs from the stored form"
        assert sanitize_html(out) == out, "sanitizer changes what the editor emits"
        page.close()
