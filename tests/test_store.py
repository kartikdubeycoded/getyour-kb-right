from sqlalchemy.pool import StaticPool
from sqlmodel import create_engine

from app import store
from app.models import RadarItem, Reel, ReelStatus


def _memory_engine():
    """Fresh in-memory DB per test (StaticPool keeps the single connection alive)."""
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    store.init_db(eng)
    return eng


def test_save_sets_id_and_default_status():
    eng = _memory_engine()
    saved = store.save_reel(Reel(url="https://insta/reel/1"), eng)
    assert saved.id is not None
    assert saved.status == ReelStatus.pending
    assert store.get_reel(saved.id, eng).url == "https://insta/reel/1"


def test_list_recent_is_newest_first():
    eng = _memory_engine()
    store.save_reel(Reel(url="first"), eng)
    store.save_reel(Reel(url="second"), eng)
    assert [r.url for r in store.list_recent(eng=eng)] == ["second", "first"]


def test_get_missing_returns_none():
    eng = _memory_engine()
    assert store.get_reel(999, eng) is None


def test_find_or_create_github_item_creates_then_reuses():
    eng = _memory_engine()
    url = "https://github.com/foo/bar"
    first = store.find_or_create_github_item("foo/bar", url, eng)
    assert first.id is not None
    assert first.source == "github"
    # second call with the same url must reuse, not duplicate
    second = store.find_or_create_github_item("foo/bar", url, eng)
    assert second.id == first.id


def test_find_or_create_reuses_existing_radar_repo():
    eng = _memory_engine()
    url = "https://github.com/openai/whisper"
    item = RadarItem(source="github", title="openai/whisper", url=url, overview="cached")
    store.replace_radar("github", [item], eng)
    found = store.find_or_create_github_item("openai/whisper", url, eng)
    assert found.overview == "cached"  # reused the radar-pulled item with its cached breakdown


def test_ideas_add_list_status_and_depth_roundtrip():
    eng = _memory_engine()
    saved = store.add_ideas(
        [
            {"title": "Build X", "kind": "build", "insight": "gap", "plan": "p",
             "why_you": "w", "sources": [{"source": "github", "title": "r", "url": "u"}]},
            {"title": "Paper Y", "kind": "paper", "insight": "g2", "plan": "h",
             "why_you": "w2", "sources": []},
        ],
        eng,
    )
    assert all(i.id is not None and i.status == "new" for i in saved)
    assert {i.title for i in store.list_ideas("new", eng=eng)} == {"Build X", "Paper Y"}

    store.set_idea_status(saved[0].id, "accepted", eng)
    assert [i.title for i in store.list_ideas("accepted", eng=eng)] == ["Build X"]
    assert [i.title for i in store.list_ideas("new", eng=eng)] == ["Paper Y"]

    # the deep dive persists on the accepted idea (exercises the migrated `depth` column)
    store.set_idea_depth(saved[0].id, "WHAT TO BUILD\nx", eng)
    assert store.get_idea(saved[0].id, eng).depth.startswith("WHAT TO BUILD")
