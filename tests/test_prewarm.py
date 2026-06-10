"""Pre-warm: after a SYNC, analyze the newest stream items in the background so the likely clicks
open instantly instead of waiting on the two-pass NIM call."""

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import create_engine

from app import main, research, store
from app.models import RadarItem


def _engine(monkeypatch):
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    monkeypatch.setattr(store, "engine", eng)
    store.init_db(eng)


def _stub_analysis(monkeypatch):
    monkeypatch.setattr(research, "analyze_item", lambda *a, **k: {"overview": "draft"})
    monkeypatch.setattr(
        research, "refine_analysis", lambda *a, **k: {"overview": "DEEP", "builds": ["b"]}
    )


def test_prewarm_warms_newest_unanalyzed_only(monkeypatch):
    _engine(monkeypatch)
    _stub_analysis(monkeypatch)
    items = [RadarItem(source="news", title=f"n{i}", url=f"u{i}") for i in range(4)]
    store.replace_radar("news", items)

    # mark the newest item already analyzed — it must be skipped
    newest = store.list_all_radar()[0]
    newest.overview = "cached"
    store.save_radar_item(newest)

    main._prewarm_top(2)  # only the top 2

    top = store.list_all_radar(limit=4)
    assert top[0].overview == "cached"  # already analyzed -> untouched
    assert top[1].overview == "DEEP"  # warmed
    assert not top[2].overview and not top[3].overview  # beyond n -> left alone


def test_refresh_all_schedules_prewarm(monkeypatch):
    _engine(monkeypatch)
    monkeypatch.setattr(main, "refresh_source", lambda *a, **k: False)  # no network fetches
    ran = {"n": 0}
    monkeypatch.setattr(main, "_prewarm_top", lambda *a, **k: ran.__setitem__("n", ran["n"] + 1))

    with TestClient(main.app) as client:
        r = client.post("/refresh-all", follow_redirects=False)
        assert r.status_code == 303
    assert ran["n"] == 1  # SYNC scheduled the background pre-warm
