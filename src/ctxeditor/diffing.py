"""Block-level diff shared by version compare and the AI agent's accept/reject view.

Both inputs are sanitized editor HTML. Each top-level block is one unit. A change is a hunk: added, removed or
modified. A modified text block also carries inline word-level <ins>/<del> markup for display. Tables, code,
diagrams and charts are compared and replaced as whole blocks.

"Accepting" a hunk means taking the proposed side. apply_decisions() rebuilds the HTML from the base plus the
accepted hunks, so the result is always built from blocks that came out of the sanitizer.
"""
from __future__ import annotations

import html as html_lib
import re
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher

from lxml import html as lxml_html

INLINE_TAGS = {"p", "h1", "h2", "h3", "h4", "blockquote", "ul", "ol"}
SIMILAR = 0.5  # a changed block is "modified" (not removed+added) when its text is at least this similar


@dataclass(frozen=True)
class Segment:
    kind: str  # equal | added | removed | modified
    hunk_id: str | None
    old_html: str
    new_html: str
    inline_html: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def split_blocks(html: str) -> list[str]:
    """Top-level blocks as serialized HTML. Stray top-level text is wrapped in a paragraph."""
    if not html or not html.strip():
        return []
    root = lxml_html.fragment_fromstring(html, create_parent="div")
    blocks: list[str] = []
    if root.text and root.text.strip():
        blocks.append(f"<p>{html_lib.escape(root.text.strip(), quote=False)}</p>")
    for child in root:
        blocks.append(lxml_html.tostring(child, encoding="unicode", with_tail=False))
        if child.tail and child.tail.strip():
            blocks.append(f"<p>{html_lib.escape(child.tail.strip(), quote=False)}</p>")
    return blocks


def _text(block: str) -> str:
    return re.sub(r"\s+", " ", lxml_html.fromstring(f"<div>{block}</div>").text_content()).strip()


def _tag(block: str) -> str:
    match = re.match(r"<([a-zA-Z0-9]+)", block)
    return match.group(1).lower() if match else ""


def _kind(block: str) -> str:
    """Tag, plus the block type for custom divs, so a diagram is never paired with a chart."""
    tag = _tag(block)
    if tag == "div":
        match = re.match(r'<div[^>]*data-type="([a-z]+)"', block)
        return f"div:{match.group(1)}" if match else "div"
    return tag


_TOKEN = re.compile(r"<[^>]+>|\s+|[^<\s]+")


def _inline(old: str, new: str) -> str | None:
    """Word-level markup. Structure (tags) comes from the new block only, so the result stays well-formed."""
    if _tag(old) != _tag(new) or _tag(new) not in INLINE_TAGS:
        return None
    a, b = _TOKEN.findall(old), _TOKEN.findall(new)
    out: list[str] = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out.extend(b[j1:j2])
        else:
            deleted = "".join(t for t in a[i1:i2] if not t.startswith("<"))
            if deleted.strip():
                out.append(f"<del>{deleted}</del>")
            run: list[str] = []
            for token in b[j1:j2]:
                if token.startswith("<") or token.isspace() and not run:
                    if run:
                        out.append(f"<ins>{''.join(run)}</ins>")
                        run = []
                    out.append(token)
                else:
                    run.append(token)
            if run:
                out.append(f"<ins>{''.join(run)}</ins>")
    return "".join(out)


def _pair(old: list[str], new: list[str]) -> list[tuple[int | None, int | None]]:
    """Order-preserving alignment of two short block lists by text similarity (DP on a weighted LCS)."""
    n, m = len(old), len(new)
    sim = [[0.0] * m for _ in range(n)]
    for i in range(n):
        for j in range(m):
            if _kind(old[i]) == _kind(new[j]):
                r = SequenceMatcher(None, _text(old[i]), _text(new[j]), autojunk=False).ratio()
                if _tag(old[i]) not in INLINE_TAGS:  # tables, code, diagrams, charts are replaced as a whole
                    r = max(r, SIMILAR)
                sim[i][j] = r if r >= SIMILAR else 0.0
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            best[i][j] = max(best[i + 1][j], best[i][j + 1], best[i + 1][j + 1] + sim[i][j] if sim[i][j] else 0.0)
    pairs: list[tuple[int | None, int | None]] = []
    i = j = 0
    while i < n and j < m:
        if sim[i][j] and best[i][j] == best[i + 1][j + 1] + sim[i][j]:
            pairs.append((i, j))
            i, j = i + 1, j + 1
        elif best[i][j] == best[i + 1][j]:
            pairs.append((i, None))
            i += 1
        else:
            pairs.append((None, j))
            j += 1
    pairs.extend((k, None) for k in range(i, n))
    pairs.extend((None, k) for k in range(j, m))
    return pairs


def diff_html(old_html: str, new_html: str) -> list[Segment]:
    """Ordered segments covering the whole document. Hunks are the non-equal ones, numbered h1, h2, ..."""
    old, new = split_blocks(old_html), split_blocks(new_html)
    raw: list[tuple[str, str, str]] = []  # (kind, old, new)
    for op, i1, i2, j1, j2 in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if op == "equal":
            raw.extend(("equal", old[i], new[j]) for i, j in zip(range(i1, i2), range(j1, j2)))
        elif op == "delete":
            raw.extend(("removed", old[i], "") for i in range(i1, i2))
        elif op == "insert":
            raw.extend(("added", "", new[j]) for j in range(j1, j2))
        else:
            for i, j in _pair(old[i1:i2], new[j1:j2]):
                if i is not None and j is not None:
                    raw.append(("modified", old[i1 + i], new[j1 + j]))
                elif i is not None:
                    raw.append(("removed", old[i1 + i], ""))
                else:
                    raw.append(("added", "", new[j1 + j]))
    segments: list[Segment] = []
    counter = 0
    for kind, o, n in raw:
        if kind == "equal":
            segments.append(Segment("equal", None, o, n))
            continue
        counter += 1
        inline = _inline(o, n) if kind == "modified" else None
        segments.append(Segment(kind, f"h{counter}", o, n, inline))
    return segments


def hunks(segments: list[Segment]) -> list[Segment]:
    return [s for s in segments if s.hunk_id]


def apply_decisions(segments: list[Segment], accepted: set[str]) -> str:
    """HTML after taking the proposed side of every accepted hunk and keeping the base for the rest."""
    out: list[str] = []
    for s in segments:
        take_new = s.kind == "equal" or s.hunk_id in accepted
        if take_new:
            out.append(s.new_html)  # for "removed" the proposed side is empty
        else:
            out.append(s.old_html)
    return "".join(out)


def accept_all(segments: list[Segment]) -> str:
    return apply_decisions(segments, {s.hunk_id for s in segments if s.hunk_id})
