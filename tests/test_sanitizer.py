from __future__ import annotations

import pytest

from ctxeditor.errors import ValidationFailed
from ctxeditor.sanitizer import MAX_HTML_CHARS, sanitize_html

XSS = [
    '<script>alert(1)</script><p>x</p>',
    '<img src=x onerror=alert(1)>',
    '<p onclick="alert(1)">x</p>',
    '<a href="javascript:alert(1)">x</a>',
    '<a href="data:text/html;base64,PHNjcmlwdD4=">x</a>',
    '<iframe src="https://evil.example"></iframe>',
    '<svg onload=alert(1)></svg>',
    '<style>body{display:none}</style><p>x</p>',
    '<p style="background:url(javascript:alert(1))">x</p>',
    '<span style="color: red; position: fixed; top: 0">x</span>',
    '<form action="/x"><input name=a></form>',
    '<div data-type="mermaid"><img src=x onerror=alert(1)></div>',
    '<math><mi xlink:href="javascript:alert(1)">x</mi></math>',
]


@pytest.mark.parametrize("payload", XSS)
def test_known_payloads_are_neutralised(payload):
    out = sanitize_html(payload).lower()
    for bad in ("<script", "onerror", "onclick", "onload", "javascript:", "<iframe", "<svg", "<style", "<form",
                "<input", "<img", "position", "url(", "<math"):
        assert bad not in out


@pytest.mark.parametrize("payload", XSS)
def test_idempotent(payload):
    once = sanitize_html(payload)
    assert sanitize_html(once) == once


def test_links_get_target_and_rel():
    out = sanitize_html('<a href="https://example.com">x</a>')
    assert 'target="_blank"' in out and 'rel="noopener noreferrer"' in out


def test_style_keeps_only_safe_properties():
    out = sanitize_html('<span style="color: #ff0000; font-size: 99px">x</span>')
    assert 'style="color: rgb(255, 0, 0);"' in out and "font-size" not in out
    assert "style" not in sanitize_html('<span style="font-size: 99px">x</span>')


def test_chart_validated_and_canonicalised():
    good = '<div data-type="chart" data-chart=\'{"type":"bar","title":"t","labels":["a"],"series":[{"name":"s","values":[1]}]}\'></div>'
    assert "data-chart" in sanitize_html(good)
    for bad in ('<div data-type="chart"></div>',
                '<div data-type="chart" data-chart="not json"></div>',
                '<div data-type="chart" data-chart=\'{"type":"radar","labels":[],"series":[]}\'></div>',
                '<div data-type="chart" data-chart=\'{"type":"bar","labels":["a"],"series":[{"name":"s","values":["x"]}]}\'></div>'):
        with pytest.raises(ValidationFailed):
            sanitize_html(bad)


def test_mermaid_source_kept_as_text_and_size_capped():
    out = sanitize_html('<div data-type="mermaid">graph TD; A--&gt;B</div>')
    assert out == '<div data-type="mermaid">graph TD; A--&gt;B</div>'
    with pytest.raises(ValidationFailed):
        sanitize_html('<div data-type="mermaid">' + "a" * 20_001 + "</div>")


def test_oversize_rejected():
    with pytest.raises(ValidationFailed):
        sanitize_html("a" * (MAX_HTML_CHARS + 1))


def test_data_attributes_on_other_tags_dropped():
    assert sanitize_html('<p data-chart="x">t</p>') == "<p>t</p>"
    assert sanitize_html('<div data-type="evil">t</div>') == "<div>t</div>"


def test_colors_are_canonicalised_like_browsers_do():
    cases = {
        "color: #f00": "color: rgb(255, 0, 0);",
        "color: #FF000080": "color: rgba(255, 0, 0, 0.502);",
        "background-color: rgb( 1,2 ,3 )": "background-color: rgb(1, 2, 3);",
        "text-align: CENTER": "text-align: center;",
        "color: red": None,
        "color: #12": None,
        "color: rgba(1,2,3,2)": None,
    }
    for given, expected in cases.items():
        out = sanitize_html(f'<span style="{given}">x</span>')
        assert out == (f'<span style="{expected}">x</span>' if expected else "<span>x</span>"), given
