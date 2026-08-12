"""The YC RFS radar's job is faithful parsing: the page is server-rendered HTML whose quirks
(<!-- --> comments inside the partner name, a trailing '#' anchor in the title) have to be handled
exactly or the card shows garbage. These tests pin that parsing against a fixture copied from the
real markup — no network, no calls."""

from app import yc_rfs

PROFILE = {"focus": "AI engineering, agents"}

# A trimmed-down capture of the real https://www.ycombinator.com/rfs markup (verified 2026-08-12):
# every request is a <div id="SLUG">, the h3 title is followed by a '#' anchor, and the author is
# 'By<!-- --> <a>First<!-- --> <!-- -->Last</a>' — the comments are real and must be stripped.
FIXTURE = """
<html><body>
<h1>Requests for Startups</h1>
<h2>Fall 2026</h2>
<div id="the-primer">
  <div class="w-full">
    <div class="mb-6">
      <h3 class="text-xl">The Primer<span class="inline-block">
        <a href="#the-primer" class="ml-2">#</a></span></h3>
      <span class="font-light">By<!-- -->
        <a href="https://www.ycombinator.com/people/andrew-miklas">
        Andrew<!-- --> <!-- -->Miklas</a></span>
    </div>
    <div class="prose"><div class="whitespace-pre-wrap">An intro essay, not a request.</div></div>
  </div>
</div>
<div id="multiplayer-ai">
  <div class="w-full">
    <div class="mb-6">
      <h3 class="text-xl">Multiplayer AI<span class="inline-block">
        <a href="#multiplayer-ai" class="ml-2">#</a></span></h3>
      <span class="font-light">By<!-- -->
        <a href="https://www.ycombinator.com/people/aaron-epstein">
        Aaron<!-- --> <!-- -->Epstein</a></span>
    </div>
    <div class="prose"><div class="whitespace-pre-wrap">
      The best work tools of the last two decades won by going multiplayer.
      AI agents are the new tool teams use together.
    </div></div>
  </div>
</div>
<div id="cooking-for-seniors">
  <div class="w-full">
    <div class="mb-6">
      <h3 class="text-xl">Cooking for Seniors<span class="inline-block">
        <a href="#cooking-for-seniors" class="ml-2">#</a></span></h3>
      <span class="font-light">By<!-- -->
        <a href="https://www.ycombinator.com/people/jane-doe">
        Jane<!-- --> <!-- -->Doe</a></span>
    </div>
    <div class="prose"><div class="whitespace-pre-wrap">
      Slow-cooked soups and bread baking for an aging population.
    </div></div>
  </div>
</div>
</body></html>
"""


def _fake_page(monkeypatch, html=FIXTURE):
    """Route the fetch to the inline fixture so no request leaves the machine."""
    monkeypatch.setattr(yc_rfs, "_get_html", lambda url: html)


def test_titles_are_parsed_without_the_trailing_anchor_hash(monkeypatch):
    _fake_page(monkeypatch)

    items = yc_rfs.fetch_yc_rfs(PROFILE)

    titles = [i.title for i in items]
    assert "Multiplayer AI" in titles
    # If the anchor strip breaks, every title comes back as "X#" — this catches it for all entries.
    assert all(not t.endswith("#") for t in titles)


def test_partner_name_strips_the_html_comments(monkeypatch):
    """'Aaron<!-- --> <!-- -->Epstein' must join as 'Aaron Epstein', not 'AaronEpstein' or a
    comment-laden blob."""
    _fake_page(monkeypatch)

    item = next(i for i in yc_rfs.fetch_yc_rfs(PROFILE) if i.title == "Multiplayer AI")

    assert "by Aaron Epstein" in item.meta


def test_url_is_the_page_url_plus_slug_anchor(monkeypatch):
    _fake_page(monkeypatch)

    item = next(i for i in yc_rfs.fetch_yc_rfs(PROFILE) if i.title == "Multiplayer AI")

    assert item.url == "https://www.ycombinator.com/rfs#multiplayer-ai"


def test_the_primer_intro_is_excluded(monkeypatch):
    _fake_page(monkeypatch)

    items = yc_rfs.fetch_yc_rfs(PROFILE)

    assert "The Primer" not in [i.title for i in items]


def test_topic_match_scores_higher_than_no_match(monkeypatch):
    """The whole point of the score: a request about AI agents must outrank one about soup."""
    _fake_page(monkeypatch)

    items = yc_rfs.fetch_yc_rfs(PROFILE)
    ai = next(i for i in items if i.title == "Multiplayer AI")
    food = next(i for i in items if i.title == "Cooking for Seniors")

    assert ai.score > food.score


def test_summary_and_batch_land_in_the_card_fields(monkeypatch):
    _fake_page(monkeypatch)

    item = next(i for i in yc_rfs.fetch_yc_rfs(PROFILE) if i.title == "Multiplayer AI")

    assert "Fall 2026" in item.meta  # the page-level <h2> becomes the batch label
    assert item.summary == (
        "The best work tools of the last two decades won by going multiplayer. "
        "AI agents are the new tool teams use together."
    )
    assert item.published_at is None  # the page states no date; we never fabricate one


def test_fetch_failure_returns_empty_instead_of_raising(monkeypatch):
    def boom(url):
        raise yc_rfs.RadarError("yc down")

    monkeypatch.setattr(yc_rfs, "_get_html", boom)

    assert yc_rfs.fetch_yc_rfs(PROFILE) == []
