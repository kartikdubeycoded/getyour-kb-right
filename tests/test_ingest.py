import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import create_engine

from app import store


@pytest.fixture
def client(monkeypatch):
    """App wired to a fresh in-memory DB (store reads `engine` at call time, so this swap works)."""
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    monkeypatch.setattr(store, "engine", eng)
    from app.main import app

    with TestClient(app) as c:  # context-manager runs lifespan -> init_db() on the in-memory engine
        yield c


def test_ingest_then_appears_on_dashboard(client):
    resp = client.post("/ingest", json={"url": "https://www.instagram.com/reel/ABC123/"})
    assert resp.status_code == 202
    assert resp.json()["id"] is not None

    page = client.get("/")
    assert page.status_code == 200
    assert "ABC123" in page.text  # the reel url rendered on the dashboard
    assert "done" in page.text  # stub pipeline marked it done


def test_ingest_rejects_bad_url(client):
    resp = client.post("/ingest", json={"url": "not-a-url"})
    assert resp.status_code == 422
