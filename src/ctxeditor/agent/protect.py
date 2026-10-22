"""Helpers around the model call: keep diagrams and charts out of the prompt, clean the model's answer, and mask
secret-looking strings before anything is sent."""
from __future__ import annotations

import re

from lxml import html as lxml_html

BLOCK_TYPES = ("mermaid", "chart")


def _is_block(node) -> bool:
    return node.tag == "div" and node.get("data-type") in BLOCK_TYPES


def protect_blocks(html: str) -> tuple[str, dict[str, str]]:
    """Replace every Mermaid and chart block with <div data-preserve="bN"></div>. Returns the new HTML and the
    mapping from placeholder id to the original serialized block."""
    if not html or "data-type" not in html:
        return html, {}
    root = lxml_html.fragment_fromstring(html, create_parent="div")
    mapping: dict[str, str] = {}
    for node in [n for n in root.iter("div") if _is_block(n)]:
        key = f"b{len(mapping) + 1}"
        mapping[key] = lxml_html.tostring(node, encoding="unicode", with_tail=False)
        placeholder = lxml_html.Element("div")
        placeholder.set("data-preserve", key)
        placeholder.tail = node.tail
        node.getparent().replace(node, placeholder)
    return _inner(root), mapping


def restore_blocks(html: str, mapping: dict[str, str]) -> str:
    """Put the original blocks back in place of their placeholders. A placeholder the model invented is removed."""
    if not html or "data-preserve" not in html:
        return html
    root = lxml_html.fragment_fromstring(html, create_parent="div")
    for node in [n for n in root.iter("div") if n.get("data-preserve") is not None]:
        original = mapping.get(node.get("data-preserve") or "")
        parent = node.getparent()
        if original is None:
            _remove_keep_tail(node)
            continue
        block = lxml_html.fragment_fromstring(original)
        block.tail = node.tail
        parent.replace(node, block)
    return _inner(root)


def _remove_keep_tail(node) -> None:
    parent, tail = node.getparent(), node.tail
    previous = node.getprevious()
    parent.remove(node)
    if tail:
        if previous is not None:
            previous.tail = (previous.tail or "") + tail
        else:
            parent.text = (parent.text or "") + tail


def _inner(root) -> str:
    out = [root.text] if root.text else []
    for child in root:
        out.append(lxml_html.tostring(child, encoding="unicode", with_tail=True))
    return "".join(out)


_FENCE = re.compile(r"```[a-zA-Z0-9]*\s*\n?(.*?)```", re.DOTALL)


def extract_html(model_text: str) -> str:
    """The HTML in a model answer: fenced content if fenced, else from the first '<' to the last '>'."""
    text = (model_text or "").strip()
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    elif text.startswith("```"):  # unterminated fence
        text = re.sub(r"^```[a-zA-Z0-9]*\s*\n?", "", text).strip()
    start, end = text.find("<"), text.rfind(">")
    if start == -1 or end < start:
        return ""
    return text[start:end + 1].strip()


_SECRET_PATTERNS = (
    re.compile(r"sk-or-[A-Za-z0-9_-]{6,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password)(\s*[=:]\s*)[^\s<>\"']{6,}"),
)


def redact_secrets(text: str) -> str:
    out = text
    for pattern in _SECRET_PATTERNS[:4]:
        out = pattern.sub("[REDACTED]", out)
    return _SECRET_PATTERNS[4].sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", out)
