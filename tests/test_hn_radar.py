from datetime import UTC, datetime

from app import hn_radar


def test_fetch_stories_builds_items_and_dedupes(monkeypatch):
    hit = {
        "objectID": "12345",
        "title": "Show HN: a tiny LLM agent",
        "url": "https://example.com/agent",
        "points": 420,
        "num_comments": 99,
    }
    # every topic returns the same story -> must dedupe by objectID to one
    monkeypatch.setattr(hn_radar, "_search", lambda topic, hits: [hit])
    items = hn_radar.fetch_stories({"focus": "AI, agents"})

    assert len(items) == 1
    item = items[0]
    assert item.source == "hn"
    assert item.title == "Show HN: a tiny LLM agent"
    assert item.url == "https://example.com/agent"
    assert item.score == 420
    assert "420" in item.meta
    assert "99 comments" in item.summary


def test_fetch_stories_carries_the_story_publish_time(monkeypatch):
    """Algolia reports created_at_i as unix seconds; it must reach the item so HN stories sort
    against dated items from every other source on one scale."""
    posted = datetime(2026, 7, 29, 14, 0, tzinfo=UTC)
    hit = {
        "objectID": "1",
        "title": "Show HN",
        "url": "https://e.co/x",
        "points": 5,
        "created_at_i": int(posted.timestamp()),
    }
    monkeypatch.setattr(hn_radar, "_search", lambda topic, hits: [hit])

    assert hn_radar.fetch_stories({"focus": "AI"})[0].published_at == posted


def test_fetch_stories_falls_back_to_hn_thread_when_no_url(monkeypatch):
    hit = {"objectID": "777", "title": "Ask HN: thoughts?", "points": 10, "num_comments": 3}
    monkeypatch.setattr(hn_radar, "_search", lambda topic, hits: [hit])
    items = hn_radar.fetch_stories({"focus": "AI"})
    assert items[0].url == "https://news.ycombinator.com/item?id=777"  # no story url -> HN thread


def test_fetch_stories_searches_the_given_topics_not_just_focus(monkeypatch):
    searched: list[str] = []

    def fake_search(topic, hits):
        searched.append(topic)
        return [{"objectID": topic, "title": topic, "url": f"https://e.co/{topic}", "points": 1}]

    monkeypatch.setattr(hn_radar, "_search", fake_search)
    items = hn_radar.fetch_stories({"focus": "AI, ML"}, topics=["web design", "jobs"])

    assert searched == ["web design", "jobs"]  # lane topics drive the search
    assert {i.title for i in items} == {"web design", "jobs"}


def test_fetch_stories_skips_failing_topic(monkeypatch):
    def maybe_boom(topic, hits):
        if topic == "bad":
            raise hn_radar.RadarError("rate limited")
        return [{"objectID": "1", "title": "ok", "url": "https://e.co", "points": 5}]

    monkeypatch.setattr(hn_radar, "_search", maybe_boom)
    items = hn_radar.fetch_stories({"radar_topics": ["bad", "good"]})
    assert [i.title for i in items] == ["ok"]  # bad topic skipped, good one kept
