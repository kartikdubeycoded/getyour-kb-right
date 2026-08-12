import calendar
import time
import types
from datetime import UTC, datetime

from app import gnews_radar


def _feed(entries):
    return types.SimpleNamespace(entries=entries)


def test_fetch_news_carries_the_entry_publish_time(monkeypatch):
    """Google News is a pure recency source — without a date it can't be ordered honestly."""
    published = datetime(2026, 7, 31, 6, 0, tzinfo=UTC)
    entry = {
        "title": "a headline",
        "link": "https://e.co/h",
        "published_parsed": time.gmtime(calendar.timegm(published.timetuple())),
    }
    monkeypatch.setattr(gnews_radar.feedparser, "parse", lambda url, agent=None: _feed([entry]))

    items = gnews_radar.fetch_news({"focus": "AI"}, topics=["ai"])

    assert items[0].published_at == published


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


def test_fetch_news_searches_passed_topics_not_just_focus(monkeypatch):
    queried: list[str] = []

    def capture(url, agent=None):
        queried.append(url)
        return _feed([])

    monkeypatch.setattr(gnews_radar.feedparser, "parse", capture)
    # lane topics injected — these, not the focus line, must drive the search queries
    gnews_radar.fetch_news({"focus": "AI"}, topics=["web design", "UX"])

    assert any("web+design" in u or "web%20design" in u for u in queried)  # lane topic searched
    assert any("UX" in u for u in queried)
    assert not any("AI" in u for u in queried)  # focus line was overridden, not appended
