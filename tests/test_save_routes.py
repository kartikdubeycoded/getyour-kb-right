"""End-to-end save flow over the HTTP routes: ☆ save -> /saved shows it -> ✕ unsave removes it."""

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import create_engine

from app import store
from app.main import app
from app.models import RadarItem


def _client(monkeypatch):
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    monkeypatch.setattr(store, "engine", eng)
    return TestClient(app)


def test_save_then_view_then_unsave(monkeypatch):
    with _client(monkeypatch) as client:
        store.replace_radar(
            "github",
            [RadarItem(source="github", title="FastAPI", url="https://github.com/t/f", meta="m")],
        )
        item = store.list_radar("github")[0]

        # ☆ save -> redirect, not an error
        r = client.post("/save", data={"item_id": item.id}, follow_redirects=False)
        assert r.status_code == 303

        # the saved view now shows it
        page = client.get("/saved")
        assert page.status_code == 200 and "FastAPI" in page.text

        # ✕ unsave -> gone
        client.post("/unsave", data={"url": item.url}, follow_redirects=False)
        assert "FastAPI" not in client.get("/saved").text


def test_feed_card_renders_a_save_button(monkeypatch):
    with _client(monkeypatch) as client:
        store.replace_radar(
            "news", [RadarItem(source="news", title="A headline", url="https://x/a", meta="m")]
        )
        html = client.get("/news").text
        assert 'action="/save"' in html  # every feed card offers to save
