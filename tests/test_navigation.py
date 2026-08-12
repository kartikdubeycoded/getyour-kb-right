from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import create_engine

from app import store
from app.main import app


def _client(monkeypatch):
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    monkeypatch.setattr(store, "engine", eng)
    return TestClient(app)


def _active_tab(html: str) -> str:
    marker = 'class="tab active" href="'
    start = html.index(marker) + len(marker)
    end = html.index('"', start)
    return html[start:end]


def test_collection_pages_share_one_active_nav_tab(monkeypatch):
    with _client(monkeypatch) as client:
        expected = {
            "/reels": "/reels",
            "/lanes": "/lanes",
            "/saved": "/saved",
            "/pulse": "/lanes",
            "/search?q=agent": "/lanes",
            "/github": "/github",
            "/hn": "/hn",
            "/reddit": "/reddit",
            "/news": "/news",
            "/opps": "/opps",
        }

        for path, active_href in expected.items():
            page = client.get(path)
            assert page.status_code == 200
            assert page.text.count('class="tab active"') == 1
            assert _active_tab(page.text) == active_href
