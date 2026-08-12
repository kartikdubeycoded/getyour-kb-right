import calendar
import time
import types
from datetime import UTC, datetime

from app import rss_radar


def _feed(entries):
    """Minimal stand-in for what feedparser.parse returns: an object with .entries."""
    return types.SimpleNamespace(entries=entries)


def test_fetch_news_builds_items_scores_strips_html_and_dedupes(monkeypatch):
    chip = {
        "title": "New NVIDIA AI chip unveiled",
        "link": "https://e.co/chip",
        "summary": "<p>The <b>agents</b> era begins</p>",
        "published_parsed": time.gmtime(2_000_000),
    }
    food = {"title": "Cooking tips", "link": "https://e.co/food", "summary": "no match here"}
    # same link returned twice (e.g. across feeds) -> must dedupe by link to one item
    feed = _feed([chip, food, chip])
    monkeypatch.setattr(rss_radar.feedparser, "parse", lambda url, agent=None: feed)
    profile = {"focus": "AI, agents", "news_feeds": [{"name": "TechWire", "url": "http://x"}]}

    items = rss_radar.fetch_news(profile)

    assert len(items) == 2  # chip + food, duplicate chip dropped
    assert {i.source for i in items} == {"news"}
    got = next(i for i in items if "chip" in i.url)
    assert got.title == "New NVIDIA AI chip unveiled"
    assert got.meta == "📰 TechWire"
    assert got.summary == "The agents era begins"  # HTML tags stripped
    assert got.score == 2  # both "AI" and "agents" matched -> floats above the food item


def test_fetch_news_carries_the_entry_publish_time(monkeypatch):
    """The feed's own date reaches the item, so the corpus can sort by when things were published
    rather than by the order our fetch loop happened to insert them."""
    published = datetime(2026, 7, 30, 9, 15, tzinfo=UTC)
    entry = {
        "title": "Anthropic ships something",
        "link": "https://e.co/a",
        "summary": "",
        "published_parsed": time.gmtime(calendar.timegm(published.timetuple())),
    }
    monkeypatch.setattr(rss_radar.feedparser, "parse", lambda url, agent=None: _feed([entry]))

    items = rss_radar.fetch_news({"focus": "AI", "news_feeds": [{"name": "X", "url": "http://x"}]})

    assert items[0].published_at == published


def test_fetch_news_survives_a_feed_with_no_date(monkeypatch):
    """Plenty of feeds omit the date. The item must still be collected, just undated."""
    entry = {"title": "undated", "link": "https://e.co/u", "summary": ""}
    monkeypatch.setattr(rss_radar.feedparser, "parse", lambda url, agent=None: _feed([entry]))

    items = rss_radar.fetch_news({"focus": "AI", "news_feeds": [{"name": "X", "url": "http://x"}]})

    assert len(items) == 1
    assert items[0].published_at is None


def test_default_feeds_have_new_sources_and_are_well_formed():
    """The six feeds added on 2026-08-12 are present, and every default feed is a (name, https url)
    2-tuple of non-empty strings — exactly the shape fetch_news relies on."""
    names = {name for name, _url in rss_radar.DEFAULT_FEEDS}
    assert {
        "Google Research",
        "Lobsters",
        "TLDR",
        "Import AI",
        "Cloudflare",
        "Smashing Magazine",
    } <= names

    for name, url in rss_radar.DEFAULT_FEEDS:
        assert isinstance(name, str) and name.strip() != ""
        assert isinstance(url, str) and url.strip() != ""
        assert url.startswith("https://")


def test_fetch_news_skips_failing_feed(monkeypatch):
    def maybe_boom(url, agent=None):
        if "bad" in url:
            raise ValueError("feed unreachable")
        return _feed([{"title": "ok", "link": "https://e.co/ok", "summary": ""}])

    monkeypatch.setattr(rss_radar.feedparser, "parse", maybe_boom)
    profile = {"focus": "AI", "news_feeds": ["http://bad/feed", "http://good/feed"]}

    items = rss_radar.fetch_news(profile)

    assert [i.title for i in items] == ["ok"]  # bad feed skipped, good one kept
