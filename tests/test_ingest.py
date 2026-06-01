import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import create_engine

from app import store


@pytest.fixture
def client(monkeypatch, tmp_path):
    """App wired to a fresh in-memory DB, with the network download mocked to succeed."""
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    monkeypatch.setattr(store, "engine", eng)

    import app.ingest as ingest_mod

    def fake_download(url, *args, **kwargs):
        p = tmp_path / "audio.m4a"
        p.write_bytes(b"x")
        return p

    monkeypatch.setattr(ingest_mod, "download_audio", fake_download)
    monkeypatch.setattr(ingest_mod, "transcribe_audio", lambda path: "transcript text")

    from app.research import ResearchResult

    def fake_research(transcript, profile, **kwargs):
        return ResearchResult(summary="s", tools_links=["t"], tag="tool", take="do it")

    monkeypatch.setattr(ingest_mod, "research_reel", fake_research)

    from app.main import app

    with TestClient(app) as c:  # context-manager runs lifespan -> init_db() on the in-memory engine
        yield c


def test_ingest_then_appears_on_dashboard(client):
    resp = client.post("/ingest", json={"url": "https://www.instagram.com/reel/ABC123/"})
    assert resp.status_code == 202
    assert resp.json()["id"] is not None

    page = client.get("/")
    assert page.status_code == 200
    assert "do it" in page.text  # the take rendered on the card
    assert "done" in page.text  # pipeline (download/transcribe/research mocked) marked it done


def test_reel_detail_shows_transcript(client):
    client.post("/ingest", json={"url": "https://www.instagram.com/reel/ABC123/"})
    page = client.get("/reel/1")
    assert page.status_code == 200
    assert "transcript text" in page.text  # full transcript on the detail page
    assert "ABC123" in page.text  # url shown on detail


def test_reel_detail_404(client):
    assert client.get("/reel/999").status_code == 404


def test_ingest_rejects_bad_url(client):
    resp = client.post("/ingest", json={"url": "not-a-url"})
    assert resp.status_code == 422


def test_ingest_marks_failed_when_download_fails(client, monkeypatch):
    import app.ingest as ingest_mod
    from app.download import DownloadError

    def boom(url, *args, **kwargs):
        raise DownloadError("private reel")

    monkeypatch.setattr(ingest_mod, "download_audio", boom)
    client.post("/ingest", json={"url": "https://www.instagram.com/reel/PRIV/"})

    page = client.get("/")
    assert "failed" in page.text
