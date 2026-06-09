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
    from app.download import Media

    def fake_download(url, *args, **kwargs):
        p = tmp_path / "audio.m4a"
        p.write_bytes(b"x")
        return Media(audio_path=p, caption="a caption", thumbnail_url=None)

    monkeypatch.setattr(ingest_mod, "download_media", fake_download)
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

    page = client.get("/reels")
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


def test_reel_mentioning_repo_shows_breakdown_button(client):
    from app.models import Reel

    reel = store.save_reel(
        Reel(url="https://insta/reel/X", caption="tool: github.com/openai/whisper")
    )
    page = client.get(f"/reel/{reel.id}")
    assert page.status_code == 200
    assert "See repo breakdown" in page.text
    assert "openai/whisper" in page.text


def test_reel_without_repo_has_no_button(client):
    from app.models import Reel

    reel = store.save_reel(Reel(url="https://insta/reel/Y", caption="a cooking reel"))
    page = client.get(f"/reel/{reel.id}")
    assert "See repo breakdown" not in page.text


def test_thumbnail_renders_on_card_and_detail(client):
    from app.models import Reel

    reel = store.save_reel(
        Reel(url="https://insta/reel/T", thumbnail_url="https://cdn/x.jpg")
    )
    assert "https://cdn/x.jpg" in client.get("/reels").text  # on the card
    assert "https://cdn/x.jpg" in client.get(f"/reel/{reel.id}").text  # on detail


def test_thumb_route_serves_saved_image(client, monkeypatch, tmp_path):
    import app.main as main_mod

    monkeypatch.setattr(main_mod, "THUMB_DIR", tmp_path)
    (tmp_path / "5.jpg").write_bytes(b"IMGBYTES")
    resp = client.get("/thumb/5")
    assert resp.status_code == 200
    assert resp.content == b"IMGBYTES"
    assert client.get("/thumb/999").status_code == 404  # missing → 404


def test_reddit_tab_shows_setup_hint_without_creds(client, monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    page = client.get("/reddit")
    assert page.status_code == 200
    assert "REDDIT_CLIENT_ID" in page.text  # the dormant setup hint


def test_ingest_rejects_bad_url(client):
    resp = client.post("/ingest", json={"url": "not-a-url"})
    assert resp.status_code == 422


def test_ingest_marks_failed_when_download_fails(client, monkeypatch):
    import app.ingest as ingest_mod
    from app.download import DownloadError

    def boom(url, *args, **kwargs):
        raise DownloadError("private reel")

    monkeypatch.setattr(ingest_mod, "download_media", boom)
    client.post("/ingest", json={"url": "https://www.instagram.com/reel/PRIV/"})

    page = client.get("/reels")
    assert "failed" in page.text
