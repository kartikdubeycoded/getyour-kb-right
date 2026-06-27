"""The focused lane page (/lane/{idx}) surfaces SIGNAL — what's heating up in that one aspect
across sources — above the items. Reads the corpus the lane already curates; no new fetch."""

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import create_engine

from app import main, store
from app.main import app
from app.models import RadarItem


def _client(monkeypatch):
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    monkeypatch.setattr(store, "engine", eng)
    # one deterministic lane so /lane/0 is stable regardless of the real profile.yaml
    profile = {"lanes": [{"name": "AI", "topics": ["agents"]}]}
    monkeypatch.setattr(main, "load_profile", lambda: profile)
    return TestClient(app)


def test_lane_page_shows_what_is_heating_up_across_sources(monkeypatch):
    with _client(monkeypatch) as client:
        # "agents" echoed by THREE distinct sources -> a real signal, not one source shouting
        store.replace_radar("github", [RadarItem(source="github", title="agents kit", url="u1")])
        store.replace_radar("hn", [RadarItem(source="hn", title="show hn: agents", url="u2")])
        store.replace_radar("news", [RadarItem(source="news", title="rise of agents", url="u3")])

        page = client.get("/lane/0")
        assert page.status_code == 200
        assert 'class="signal"' in page.text  # the heating-up strip is rendered
        assert "agents" in page.text  # the heating topic is named


def test_lane_page_omits_signal_when_corpus_is_empty(monkeypatch):
    with _client(monkeypatch) as client:
        page = client.get("/lane/0")
        assert page.status_code == 200
        assert 'class="signal"' not in page.text  # nothing heating -> no strip
