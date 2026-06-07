import time
import types

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


def test_fetch_news_skips_failing_feed(monkeypatch):
    def maybe_boom(url, agent=None):
        if "bad" in url:
            raise ValueError("feed unreachable")
        return _feed([{"title": "ok", "link": "https://e.co/ok", "summary": ""}])

    monkeypatch.setattr(rss_radar.feedparser, "parse", maybe_boom)
    profile = {"focus": "AI", "news_feeds": ["http://bad/feed", "http://good/feed"]}

    items = rss_radar.fetch_news(profile)

    assert [i.title for i in items] == ["ok"]  # bad feed skipped, good one kept
