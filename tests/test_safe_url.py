"""The URL-scheme gate on rendered links.

Item URLs are not ours — they come from RSS <link> elements, search APIs and LLM-extracted text.
Autoescaping does NOT save us here: it escapes the quotes so the attribute can't be broken out of,
but a `javascript:` value inside a well-formed href still executes on click. These pin the whole
rejected scheme class, and that a hostile URL can still never reach a rendered page.
"""

import re

from app.main import safe_url, templates
from app.models import RadarItem


def test_web_urls_pass_through_untouched():
    assert safe_url("https://example.com/a?b=c#d") == "https://example.com/a?b=c#d"
    assert safe_url("http://example.com") == "http://example.com"


def test_site_relative_paths_are_allowed():
    """Our own links (/item/12) must keep working — the gate is about SCHEMES, not about
    forbidding internal navigation."""
    assert safe_url("/item/12") == "/item/12"


def test_protocol_relative_urls_are_rejected():
    """`//evil.com` inherits the page's scheme and silently leaves the site — it looks like a path
    but behaves like an absolute URL."""
    assert safe_url("//evil.com/x") == "#"


def test_dangerous_schemes_are_all_rejected():
    for hostile in (
        "javascript:alert(1)",
        'javascript:alert("http")',  # the exact string the old `'http' in link` guard let through
        "JaVaScRiPt:alert(1)",
        "  javascript:alert(1)  ",  # padded, to prove we strip before testing
        "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
        "vbscript:msgbox(1)",
        "file:///C:/Windows/System32/",
    ):
        assert safe_url(hostile) == "#", hostile


def test_empty_and_missing_urls_are_safe():
    assert safe_url(None) == "#"
    assert safe_url("") == "#"


def test_a_hostile_url_never_reaches_a_rendered_card():
    """The real defence is that no TEMPLATE can render the scheme, not that one helper returns the
    right string. Rendered through the shared card macro every feed page uses.

    Deliberately renders the macro directly rather than driving a route: going through the app would
    mean writing this item into the real database, and `replace_radar` would delete the live corpus
    for that source. A test must never be able to destroy the user's data to prove a point.
    """
    item = RadarItem(
        id=1, source="news", title="totally normal article", url='javascript:alert("http")'
    )
    macro = templates.env.get_template("_card.html").module.radar_card

    html = str(macro(item, saved=True))  # saved=True is the branch that links straight to item.url

    assert "totally normal article" in html  # the card still renders
    assert 'href="#"' in html  # it was neutralised, not silently dropped

    # No HREF anywhere on the card carries a hostile scheme. Asserted on hrefs specifically, not on
    # the whole page: the /saved card also posts the raw url back in a hidden <input> to say WHICH
    # row to unsave. That value is an identifier, not a link — HTML-escaped and never navigable — so
    # demanding the string be absent everywhere would fail for a case that is not a vulnerability.
    hrefs = re.findall(r'href="([^"]*)"', html)
    assert hrefs, "the card should still contain links"
    assert not [h for h in hrefs if not h.startswith(("http://", "https://", "/", "#"))]


def test_a_hostile_url_cannot_reach_the_detail_page_script():
    """The scheme gate must cover URLs that travel through a data-* attribute into JavaScript.

    item_detail.html stashes item.url in data-source-url and its fallback script assigns it to
    `a.href`. Escaping alone does NOT help there: the value never touches innerHTML, but a
    `javascript:` href still executes when the link is clicked. Only the scheme gate stops it.
    """
    item = RadarItem(id=7, source="news", title="normal", url="javascript:alert(1)")

    html = templates.get_template("item_detail.html").render(
        request=None, item=item, analyzed=False
    )

    assert "javascript:alert" not in html
    assert 'data-source-url="#"' in html
