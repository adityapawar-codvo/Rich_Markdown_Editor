"""Export to PDF and Word. The content comes only from DocumentService.export_payload, which checks the caller's
actions (published content needs doc.export, a draft needs doc.export_draft) and audits the export, so no export can
bypass the permission rules.

PDF: the print page is rendered by headless Chromium with the same stylesheet and rendering bundle as the editor,
so what is on screen is what is printed. DOCX: diagrams and charts are screenshotted from that same page and placed
in a document built from real Word structures (export/docx.py).
"""
from __future__ import annotations

import asyncio
import html as html_lib
import re
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, select_autoescape

from ..documents import DocumentService
from ..models import Actor, DocMetadata
from ..timefmt import format_local, valid_zone
from .browser import DIST, ORIGIN, BrowserPool, ExportFailed
from .docx import build_docx

HERE = Path(__file__).resolve().parent

PAGE = Environment(autoescape=select_autoescape(default=True)).from_string("""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{{ title }}</title>
<link rel="stylesheet" href="{{ origin }}/static/fonts.css">
<style>{{ document_css|safe }}</style><style>{{ print_css|safe }}</style>
</head>
<body class="cx-print"><div class="cx-page">
{% if draft %}<div class="cx-draft-banner">DRAFT</div>{% endif %}
<h1 class="cx-doc-title">{{ title }}</h1>
<table class="cx-meta"><tbody>
{% for label, value in rows %}<tr><th>{{ label }}</th><td>{{ value }}</td></tr>{% endfor %}
</tbody></table>
<div class="cx-doc">{{ body|safe }}</div>
</div>
<script type="module" src="{{ origin }}/dist/export.js"></script>
</body></html>""")

MEDIA = {"pdf": "application/pdf",
         "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


@dataclass(frozen=True)
class ExportResult:
    filename: str
    media_type: str
    data: bytes


def metadata_rows(m: DocMetadata, tz: str | None) -> list[tuple[str, str]]:
    return [
        ("Type", m.doc_type), ("Version", f"v{m.version_number}"), ("Status", m.status),
        ("Created", f"{format_local(m.created_at, tz)} by {m.created_by}"),
        ("Last edited", f"{format_local(m.last_edited_at, tz)} by {m.last_edited_by}"),
        ("Last published",
         f"{format_local(m.last_published_at, tz)} by {m.last_published_by}" if m.last_published_at else "Not published"),
    ]


def filename_for(title: str, version: int, draft: bool, fmt: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower()[:60] or "document"
    return f"{slug}-v{version}{'-DRAFT' if draft else ''}.{fmt}"


class ExportService:
    def __init__(self, docs: DocumentService, pool: BrowserPool | None = None):
        self._docs = docs
        self.pool = pool or BrowserPool()

    async def export(self, actor: Actor, document_id: str, fmt: str, version: int | None = None,
                     tz: str | None = None) -> ExportResult:
        if fmt not in MEDIA:
            raise ExportFailed("Choose PDF or Word.")
        tz = valid_zone(tz)
        payload = await asyncio.to_thread(self._docs.export_payload, actor, document_id, version, fmt)
        m = payload.metadata
        page_html = PAGE.render(
            title=payload.title, origin=ORIGIN, draft=payload.is_draft, rows=metadata_rows(m, tz), body=payload.html,
            document_css=(DIST / "document.css").read_text(), print_css=(HERE / "print.css").read_text())
        name = filename_for(payload.title, m.version_number, payload.is_draft, fmt)
        async with self.pool.page(page_html) as page:
            if fmt == "pdf":
                data = await page.pdf(
                    format="A4", print_background=True, display_header_footer=True, prefer_css_page_size=False,
                    margin={"top": "22mm", "bottom": "20mm", "left": "20mm", "right": "20mm"},
                    header_template=_header(payload.title, payload.is_draft), footer_template=_footer())
                return ExportResult(name, MEDIA[fmt], data)
            images: dict[int, bytes] = {}
            blocks = await page.query_selector_all('.cx-doc div[data-type="mermaid"], .cx-doc div[data-type="chart"]')
            for index, block in enumerate(blocks):
                images[index] = await block.screenshot(type="png")
        data = await asyncio.to_thread(build_docx, payload, images, tz)
        return ExportResult(name, MEDIA[fmt], data)


def _header(title: str, draft: bool) -> str:
    left = html_lib.escape(title if len(title) < 70 else title[:67] + "...")
    right = '<span style="color:#c62828;font-weight:700;letter-spacing:.12em">DRAFT</span>' if draft else ""
    return ('<div style="font-family:Inter,Helvetica,Arial,sans-serif;font-size:8px;color:#6b7280;width:100%;'
            f'padding:0 20mm;display:flex;justify-content:space-between"><span>{left}</span>{right}</div>')


def _footer() -> str:
    return ('<div style="font-family:Inter,Helvetica,Arial,sans-serif;font-size:8px;color:#6b7280;width:100%;'
            'padding:0 20mm;text-align:center">Page <span class="pageNumber"></span> of '
            '<span class="totalPages"></span></div>')
