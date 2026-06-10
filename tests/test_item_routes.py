"""The /item/{id} depth page: analyzes once (NIM mocked), caches, renders the personal read."""

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import create_engine

from app import research, store
from app.main import app
from app.models import RadarItem


def _client(monkeypatch):
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    monkeypatch.setattr(store, "engine", eng)
    return TestClient(app)


def test_item_detail_analyzes_once_and_caches(monkeypatch):
    calls = {"n": 0}

    def fake(item, profile, client=None):
        calls["n"] += 1
        return {
            "overview": "a deep read", "usage": "matters to you",
            "builds": ["build a thing"], "product_ideas": ["sell it"],
        }

    monkeypatch.setattr(research, "analyze_item", fake)
    with _client(monkeypatch) as client:
        news = RadarItem(source="news", title="Tool X", url="https://x", meta="m")
        store.replace_radar("news", [news])
        item = store.list_radar("news")[0]

        page = client.get(f"/item/{item.id}")
        assert page.status_code == 200
        assert "a deep read" in page.text  # depth shown, not a redirect to the source
        assert "build a thing" in page.text and "sell it" in page.text  # the personal opportunity

        client.get(f"/item/{item.id}")  # second view
        assert calls["n"] == 1  # cached — analyzed only once


def test_item_detail_404_for_missing(monkeypatch):
    with _client(monkeypatch) as client:
        assert client.get("/item/99999").status_code == 404
