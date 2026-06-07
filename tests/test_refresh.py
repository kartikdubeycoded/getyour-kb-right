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


def _item(title):
    return RadarItem(source="news", title=title, url=f"http://x/{title}")


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
