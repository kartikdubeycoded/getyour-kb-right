from sqlalchemy.pool import StaticPool
from sqlmodel import create_engine

from app import store
from app.models import Reel, ReelStatus


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
