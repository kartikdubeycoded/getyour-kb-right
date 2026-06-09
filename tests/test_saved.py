"""The saved-shortlist store. A SavedItem is a durable snapshot, so it must survive a source
refresh (which wipes + re-inserts the live corpus). Saving by url is idempotent."""

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import create_engine

from app import store
from app.models import RadarItem


@pytest.fixture
def eng():
    e = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    store.init_db(e)
    return e


def _seed(eng, source="github", url="https://github.com/o/r", title="repo"):
    item = RadarItem(source=source, title=title, url=url, summary="s", meta="m")
    store.replace_radar(source, [item], eng)
    return store.list_radar(source, eng=eng)[0]


def test_save_copies_fields_and_lists_it(eng):
    item = _seed(eng)
    saved = store.save_radar(item.id, eng)
    assert saved is not None and saved.url == item.url and saved.title == "repo"
    rows = store.list_saved(eng)
    assert [r.url for r in rows] == [item.url]
    assert rows[0].source == "github" and rows[0].meta == "m"


def test_saving_twice_is_idempotent(eng):
    item = _seed(eng)
    store.save_radar(item.id, eng)
    store.save_radar(item.id, eng)  # same url again
    assert len(store.list_saved(eng)) == 1


def test_saved_survives_a_source_refresh(eng):
    """The whole point: refreshing the source wipes the live corpus, the shortlist stays."""
    item = _seed(eng, url="https://github.com/keep/me")
    store.save_radar(item.id, eng)
    # a refresh replaces the github corpus with entirely different rows
    fresh = RadarItem(source="github", title="other", url="https://github.com/x/y")
    store.replace_radar("github", [fresh], eng)
    assert store.list_radar("github", eng=eng)[0].url == "https://github.com/x/y"  # corpus changed
    assert [r.url for r in store.list_saved(eng)] == ["https://github.com/keep/me"]  # kept


def test_unsave_removes_it(eng):
    item = _seed(eng)
    store.save_radar(item.id, eng)
    store.unsave(item.url, eng)
    assert store.list_saved(eng) == []


def test_saved_urls_returns_the_set(eng):
    a = _seed(eng, url="https://github.com/a/a")
    store.save_radar(a.id, eng)
    assert store.saved_urls(eng) == {"https://github.com/a/a"}


def test_save_unknown_id_is_a_noop(eng):
    assert store.save_radar(9999, eng) is None
    assert store.list_saved(eng) == []


def test_list_saved_is_newest_first(eng):
    a = _seed(eng, url="https://github.com/a/a", title="A")
    b = _seed(eng, source="news", url="https://news/b", title="B")
    store.save_radar(a.id, eng)
    store.save_radar(b.id, eng)
    # most recently saved comes first
    assert [r.title for r in store.list_saved(eng)] == ["B", "A"]
