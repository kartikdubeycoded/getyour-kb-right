import calendar
import time
import types
from datetime import UTC, datetime

from app import arxiv_radar


def _feed(entries):
    return types.SimpleNamespace(entries=entries)


def test_fetch_papers_carries_the_submission_date(monkeypatch):
    """arXiv sets score=0 for every paper, so the submission date is the ONLY thing that can
    order the tab."""
    published = datetime(2026, 7, 28, 18, 30, tzinfo=UTC)
    entry = {
        "title": "A paper",
        "link": "https://arxiv.org/abs/1",
        "summary": "abstract",
        "published_parsed": time.gmtime(calendar.timegm(published.timetuple())),
    }
    monkeypatch.setattr(arxiv_radar.feedparser, "parse", lambda url, agent=None: _feed([entry]))

    items = arxiv_radar.fetch_papers({"focus": "AI"})

    assert items[0].published_at == published


def test_fetch_papers_builds_items_and_dedupes(monkeypatch):
    entry = {
        "title": "Scaling   Laws\nfor LLM Agents",  # messy whitespace must be collapsed
        "link": "http://arxiv.org/abs/2401.00001",
        "summary": "We study how agents scale.",
        "authors": [{"name": "A. Researcher"}, {"name": "B. Scientist"}],
    }
    # the single combined query returns the same paper twice -> dedupe by link to one
    feed = _feed([entry, entry])
    monkeypatch.setattr(arxiv_radar.feedparser, "parse", lambda url, agent=None: feed)

    items = arxiv_radar.fetch_papers({"focus": "LLM, agents"})

    assert len(items) == 1
    got = items[0]
    assert got.source == "arxiv"
    assert got.title == "Scaling Laws for LLM Agents"  # whitespace collapsed
    assert got.url == "http://arxiv.org/abs/2401.00001"
    assert "A. Researcher" in got.meta and "B. Scientist" in got.meta


def test_fetch_papers_returns_empty_on_failure(monkeypatch):
    def boom(url, agent=None):
        raise ValueError("unreachable")

    monkeypatch.setattr(arxiv_radar.feedparser, "parse", boom)
    assert arxiv_radar.fetch_papers({"focus": "AI"}) == []  # graceful, never raises
