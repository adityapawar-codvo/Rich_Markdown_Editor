"""The single HTML allowlist. Everything that is stored, shown, diffed, exported or sent to the agent goes through
sanitize_html(). It must accept exactly what the editor schema emits: tests/test_roundtrip.py ties the two together.

Storage format of the custom blocks:
  <div data-type="mermaid">diagram source as text</div>
  <div data-type="chart" data-chart='{"type":"bar",...}'></div>
Task lists store no <input>: <ul data-type="taskList"><li data-type="taskItem" data-checked="true"><div>..</div></li></ul>
"""
from __future__ import annotations

import json
import re
from typing import Literal

import nh3
from lxml import html as lxml_html
from pydantic import BaseModel, Field, ValidationError, field_validator

from .errors import ValidationFailed

MAX_HTML_CHARS = 1_000_000
MAX_MERMAID_CHARS = 20_000

TAGS = {
    "p", "h1", "h2", "h3", "h4", "blockquote", "hr", "br", "ul", "ol", "li", "strong", "em", "u", "s", "sub", "sup",
    "code", "pre", "a", "span", "mark", "table", "thead", "tbody", "tr", "th", "td", "div",
}
ATTRIBUTES = {
    "a": {"href", "target"},  # rel is managed by link_rel
    "ol": {"start"},
    "ul": {"data-type"},
    "li": {"data-type", "data-checked"},
    "th": {"colspan", "rowspan"},
    "td": {"colspan", "rowspan"},
    "span": {"style"},
    "mark": {"style"},
    "p": {"style"},
    "h1": {"style"}, "h2": {"style"}, "h3": {"style"}, "h4": {"style"},
    "code": {"class"},
    "div": {"data-type", "data-chart"},
}
URL_SCHEMES = {"http", "https", "mailto"}

_HEX = r"#[0-9a-fA-F]{3,8}"
_RGB = r"rgba?\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*(?:,\s*(?:0|1|0?\.\d+)\s*)?\)"
_COLOR = re.compile(rf"^(?:{_HEX}|{_RGB})$")
_ALIGN = re.compile(r"^(?:left|right|center|justify)$")
_LANG = re.compile(r"^language-[a-z0-9+#_-]{1,30}$")
_DIGITS = re.compile(r"^[1-9]\d{0,3}$")


def _canon_color(raw: str) -> str | None:
    """The form browsers serialize: rgb(r, g, b) or rgba(r, g, b, a). Hex input is converted."""
    raw = raw.strip()
    match = re.fullmatch(r"#([0-9a-fA-F]+)", raw)
    if match:
        digits = match.group(1)
        if len(digits) in (3, 4):
            digits = "".join(c * 2 for c in digits)
        if len(digits) not in (6, 8):
            return None
        r, g, b = (int(digits[i:i + 2], 16) for i in (0, 2, 4))
        alpha = int(digits[6:8], 16) / 255 if len(digits) == 8 else 1.0
    else:
        nums = re.fullmatch(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*([0-9.]+)\s*)?\)", raw)
        if not nums:
            return None
        r, g, b = (min(int(nums.group(i)), 255) for i in (1, 2, 3))
        alpha = float(nums.group(4)) if nums.group(4) else 1.0
        if alpha > 1:
            return None
    if alpha >= 1:
        return f"rgb({r}, {g}, {b})"
    return f"rgba({r}, {g}, {b}, {round(alpha, 3):g})"


def _style_filter(value: str) -> str | None:
    """Keep only color, background-color and text-align, in the canonical form browsers produce
    (``color: rgb(1, 2, 3); text-align: center;``), so editor output and stored output are identical."""
    kept = []
    for part in value.split(";"):
        if not part.strip():
            continue
        name, _, raw = part.partition(":")
        name, raw = name.strip().lower(), raw.strip()
        if name in ("color", "background-color"):
            color = _canon_color(raw)
            if color:
                kept.append(f"{name}: {color};")
        elif name == "text-align" and _ALIGN.match(raw.lower()):
            kept.append(f"text-align: {raw.lower()};")
    return " ".join(kept) if kept else None


def _attribute_filter(tag: str, attr: str, value: str) -> str | None:
    if attr == "style":
        return _style_filter(value)
    if attr == "data-type":
        allowed = {"ul": {"taskList"}, "li": {"taskItem"}, "div": {"mermaid", "chart"}}
        return value if value in allowed.get(tag, set()) else None
    if attr == "data-checked":
        return value if value in ("true", "false") else None
    if attr == "class":
        kept = [c for c in value.split() if _LANG.match(c)]
        return " ".join(kept) if kept else None
    if attr in ("colspan", "rowspan", "start"):
        return value if _DIGITS.match(value) else None
    if attr == "data-chart":
        return value if len(value) <= 100_000 else None
    return value


class ChartSeries(BaseModel):
    name: str = Field(max_length=100)
    values: list[float] = Field(max_length=200)

    @field_validator("values")
    @classmethod
    def _finite(cls, values: list[float]) -> list[float]:
        for v in values:
            if v != v or v in (float("inf"), float("-inf")):
                raise ValueError("values must be finite numbers")
        return values


class ChartSpec(BaseModel):
    """The JSON stored in a chart block. Validated on every save; an invalid chart fails the save."""

    type: Literal["bar", "line", "pie", "area"]
    title: str = Field(default="", max_length=200)
    labels: list[str] = Field(max_length=200)
    series: list[ChartSeries] = Field(min_length=1, max_length=12)

    @field_validator("labels")
    @classmethod
    def _label_len(cls, labels: list[str]) -> list[str]:
        if any(len(label) > 100 for label in labels):
            raise ValueError("labels must be 100 characters or fewer")
        return labels


def canonical_chart_json(spec: ChartSpec) -> str:
    """The one stored form of a chart. Integral numbers are written without a decimal point so the editor's
    JSON.stringify produces exactly the same text."""
    data = spec.model_dump()
    for series in data["series"]:
        series["values"] = [int(v) if float(v).is_integer() and abs(v) < 1e15 else v for v in series["values"]]
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def parse_chart(raw: str) -> ChartSpec:
    try:
        return ChartSpec.model_validate(json.loads(raw))
    except (ValueError, ValidationError) as exc:
        raise ValidationFailed("A chart block has invalid data. Open it and check the values.", field="content") from exc


def _clean(html: str) -> str:
    return nh3.clean(
        html,
        tags=TAGS,
        attributes=ATTRIBUTES,
        attribute_filter=_attribute_filter,
        url_schemes=URL_SCHEMES,
        link_rel="noopener noreferrer",
        set_tag_attribute_values={"a": {"target": "_blank"}},
        strip_comments=True,
        clean_content_tags={"script", "style"},
    )


def _validate_blocks(cleaned: str) -> str:
    if "data-type" not in cleaned:
        return cleaned
    root = lxml_html.fragment_fromstring(cleaned, create_parent="div")
    changed = False
    for node in root.iter("div"):
        kind = node.get("data-type")
        if kind == "mermaid":
            source = node.text_content()
            if len(source) > MAX_MERMAID_CHARS:
                raise ValidationFailed("A diagram is too large (20,000 characters at most).", field="content")
            if len(node):  # source must be plain text
                for child in list(node):
                    node.remove(child)
                node.text = source
                changed = True
            if "data-chart" in node.attrib:
                del node.attrib["data-chart"]
                changed = True
        elif kind == "chart":
            raw = node.get("data-chart")
            if raw is None:
                raise ValidationFailed("A chart block has no data.", field="content")
            spec = parse_chart(raw)
            canonical = canonical_chart_json(spec)
            if canonical != raw:
                node.set("data-chart", canonical)
                changed = True
            if len(node) or (node.text or "").strip():
                for child in list(node):
                    node.remove(child)
                node.text = None
                changed = True
        elif "data-chart" in node.attrib:
            del node.attrib["data-chart"]
            changed = True
    if not changed:
        return cleaned
    return "".join(
        lxml_html.tostring(child, encoding="unicode") if isinstance(child, lxml_html.HtmlElement) else str(child)
        for child in _children_with_text(root)
    )


def _children_with_text(root):
    if root.text:
        yield root.text
    for child in root:
        yield child
        if child.tail:
            yield child.tail


def sanitize_html(html: str | None) -> str:
    """Allowlist-sanitize editor HTML. Idempotent. Raises ValidationFailed for oversize input or a bad chart."""
    html = html or ""
    if len(html) > MAX_HTML_CHARS:
        raise ValidationFailed("The document is too large (1,000,000 characters at most).", field="content")
    return _validate_blocks(_clean(html))
