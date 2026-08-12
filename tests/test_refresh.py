from sqlalchemy.pool import StaticPool
from sqlmodel import create_engine

from app import main, store
from app.models import RadarItem


def _memory_engine():
    """Fresh in-memory DB per test (StaticPool keeps the single connection alive)."""
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    store.init_db(eng)
    return eng


def _item(title, source="news"):
    # `source` matters: replace_radar deletes by the source KEY but inserts each item under its own
    # item.source, so a stub tagged with the wrong one lands in another source's bucket.
    return RadarItem(source=source, title=title, url=f"http://x/{title}")


def test_refresh_source_replaces_when_fetch_has_items():
    eng = _memory_engine()
    store.replace_radar("news", [_item("old")], eng)
    updated = main.refresh_source("news", lambda: [_item("fresh")], eng)
    assert updated is True
    assert [i.title for i in store.list_radar("news", eng=eng)] == ["fresh"]


def test_refresh_source_keeps_existing_when_fetch_is_empty():
    eng = _memory_engine()
    store.replace_radar("news", [_item("keep me")], eng)
    # a transient failure (e.g. arXiv 429) comes back empty — it must NOT wipe the good data
    updated = main.refresh_source("news", lambda: [], eng)
    assert updated is False
    assert [i.title for i in store.list_radar("news", eng=eng)] == ["keep me"]


def test_refresh_source_survives_fetch_exception():
    eng = _memory_engine()
    store.replace_radar("news", [_item("keep me")], eng)

    def boom():
        raise RuntimeError("network down")

    updated = main.refresh_source("news", boom, eng)  # must not raise, must not wipe
    assert updated is False
    assert [i.title for i in store.list_radar("news", eng=eng)] == ["keep me"]


# --- refresh_everything: the whole job, with no HTTP layer involved ---


def _stub_all_sources(monkeypatch, **overrides):
    """Point every fetcher at a one-item stub so the batch runs offline. Individual sources can be
    overridden to fail/return nothing."""
    defaults = {
        "github_radar.fetch_trending": lambda *a, **k: [_item("trending", "trending")],
        "github_radar.fetch_repos": lambda *a, **k: [_item("repo", "github")],
        "hn_radar.fetch_stories": lambda *a, **k: [_item("story", "hn")],
        "rss_radar.fetch_news": lambda *a, **k: [_item("news", "news")],
        "arxiv_radar.fetch_papers": lambda *a, **k: [_item("paper", "arxiv")],
        "gnews_radar.fetch_news": lambda *a, **k: [_item("gnews", "gnews")],
        "opportunity_radar.fetch_opportunities": lambda *a, **k: [_item("hackathon", "opps")],
        "yc_rfs.fetch_yc_rfs": lambda *a, **k: [_item("request", "ycrfs")],
    }
    for target, fn in {**defaults, **overrides}.items():
        monkeypatch.setattr(f"app.main.{target}", fn)
    monkeypatch.setattr("app.main.reddit_radar.has_credentials", lambda: False)
    monkeypatch.setattr("app.main.load_profile", lambda: {"focus": "AI"})


def test_refresh_everything_runs_without_a_request(monkeypatch):
    """The whole point of the extraction: the scheduler must be able to call this with no HTTP
    layer, no Request, and no BackgroundTasks."""
    eng = _memory_engine()
    _stub_all_sources(monkeypatch)

    results = main.refresh_everything(eng=eng)

    assert results["news"] is True
    assert set(results) == {
        "trending",
        "github",
        "hn",
        "news",
        "arxiv",
        "gnews",
        "opps",
        "ycrfs",
    }


def test_refresh_everything_reports_which_sources_landed(monkeypatch):
    """A per-source verdict is what lets the heartbeat log 'github failed' instead of
    going quiet."""
    eng = _memory_engine()

    def dead(*_a, **_k):
        raise RuntimeError("rate limited")

    _stub_all_sources(monkeypatch, **{"github_radar.fetch_repos": dead})

    results = main.refresh_everything(eng=eng)

    assert results["github"] is False  # failed
    assert results["news"] is True  # unaffected by its neighbour


def test_refresh_everything_keeps_a_failed_sources_existing_items(monkeypatch):
    """The corpus-shrink guard must survive the refactor: a source that fails keeps what it had."""
    eng = _memory_engine()
    store.replace_radar("news", [_item("previously fetched")], eng)
    _stub_all_sources(monkeypatch, **{"rss_radar.fetch_news": lambda *a, **k: []})

    main.refresh_everything(eng=eng)

    assert [i.title for i in store.list_radar("news", eng=eng)] == ["previously fetched"]


def test_refresh_everything_skips_reddit_without_credentials(monkeypatch):
    """Reddit is dormant until creds are set; it must not appear in the results at all."""
    eng = _memory_engine()
    _stub_all_sources(monkeypatch)

    assert "reddit" not in main.refresh_everything(eng=eng)
