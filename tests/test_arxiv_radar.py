import types

from app import arxiv_radar


def _feed(entries):
    return types.SimpleNamespace(entries=entries)


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
