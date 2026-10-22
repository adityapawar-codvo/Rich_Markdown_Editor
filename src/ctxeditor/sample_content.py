"""Sample document for the demo and for tests. Uses every node and mark of the editor schema, so the
round-trip contract test (editor output == sanitizer output) covers the whole allowlist."""
from __future__ import annotations

import html
import json

_CHART = json.dumps(
    {"type": "bar", "title": "Quarterly signups", "labels": ["Q1", "Q2", "Q3", "Q4"],
     "series": [{"name": "Web", "values": [120, 150, 180, 210]},
                {"name": "Mobile", "values": [80, 110, 160, 230]}]},
    separators=(",", ":"))

_PIE = json.dumps(
    {"type": "pie", "title": "Traffic sources", "labels": ["Search", "Direct", "Referral"],
     "series": [{"name": "Share", "values": [55, 30, 15]}]}, separators=(",", ":"))

MERMAID = """sequenceDiagram
  participant U as User
  participant A as App
  participant I as Identity
  U->>A: Open the portal
  A->>I: Redirect to sign in
  I-->>A: Signed token
  A-->>U: Show dashboard"""

SAMPLE_HTML = (
    "<h1>Customer Portal: context editor showcase</h1>"
    "<p>This document uses <strong>bold</strong>, <em>italic</em>, <u>underline</u>, <s>strikethrough</s>, "
    "H<sub>2</sub>O, x<sup>2</sup>, <code>inline code</code>, a "
    '<a href="https://example.com" target="_blank" rel="noopener noreferrer">link</a>, '
    '<span style="color: rgb(198, 40, 40);">colored text</span> and '
    '<mark style="background-color: rgb(255, 245, 157);">highlighted text</mark>.</p>'
    '<p style="text-align: center;">A centered paragraph.</p>'
    "<h2>Goals</h2>"
    "<ul><li><p>Single place for project context</p></li><li><p>Versioned and reviewable</p>"
    "<ul><li><p>Draft and publish</p></li></ul></li></ul>"
    "<ol><li><p>Write</p></li><li><p>Review</p></li><li><p>Publish</p></li></ol>"
    '<ul data-type="taskList"><li data-type="taskItem" data-checked="true"><div><p>Draft the PRD</p></div></li>'
    '<li data-type="taskItem" data-checked="false"><div><p>Collect feedback</p></div></li></ul>'
    "<blockquote><p>Good context makes good decisions.</p></blockquote>"
    "<h3>Risks</h3>"
    "<table><tbody>"
    "<tr><th><p>Risk</p></th><th><p>Impact</p></th><th><p>Mitigation</p></th></tr>"
    "<tr><td><p>Vendor lock-in</p></td><td><p>High</p></td><td><p>Abstract the provider</p></td></tr>"
    '<tr><td colspan="2"><p>Merged cell</p></td><td><p>n/a</p></td></tr>'
    "</tbody></table>"
    "<hr>"
    "<h4>Sign-in flow</h4>"
    f'<div data-type="mermaid">{html.escape(MERMAID, quote=False)}</div>'
    f'<div data-type="chart" data-chart="{html.escape(_CHART)}"></div>'
    '<pre><code class="language-python">def greet(name):\n    return f"Hello, {name}"</code></pre>'
    "<p>End of document.</p>"
)

SAMPLE_HTML_V2 = SAMPLE_HTML.replace(
    "<p>End of document.</p>",
    "<h2>Open questions</h2><p>Which identity provider do we start with?</p>"
    f'<div data-type="chart" data-chart="{html.escape(_PIE)}"></div><p>End of document.</p>')
