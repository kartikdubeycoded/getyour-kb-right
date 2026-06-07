import types

from app import gnews_radar


def _feed(entries):
    return types.SimpleNamespace(entries=entries)


def test_fetch_news_builds_items_dedupes_and_reads_publisher(monkeypatch):
    entry = {
        "title": "Lovable raises a big round - TechCrunch",
        "link": "https://news.google.com/articles/abc",
        "source": {"title": "TechCrunch", "href": "https://techcrunch.com"},
    }
    feed = _feed([entry, entry])
    monkeypatch.setattr(gnews_radar.feedparser, "parse", lambda url, agent=None: feed)

    items = gnews_radar.fetch_news({"focus": "startups"})

    assert len(items) == 1  # duplicate link dropped
    got = items[0]
    assert got.source == "gnews"
    assert got.meta == "🔎 TechCrunch"  # publisher pulled from the <source> element


def test_fetch_news_handles_missing_source(monkeypatch):
    entry = {"title": "Some headline", "link": "https://news.google.com/articles/xyz"}
    monkeypatch.setattr(gnews_radar.feedparser, "parse", lambda url, agent=None: _feed([entry]))

    items = gnews_radar.fetch_news({"focus": "AI"})
    assert items[0].meta == "🔎 Google News"  # falls back when no publisher
