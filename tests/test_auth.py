"""The opt-in shared-secret gate on the write/trigger endpoints (/ingest, /refresh-all).
Unset INGEST_TOKEN -> open (localhost dev). Set it -> a matching X-Ingest-Token header is
required, or the request is rejected 401 before any work/fetch happens."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_ingest_open_when_token_unset(monkeypatch):
    """No INGEST_TOKEN configured -> the webhook stays open (dev on localhost)."""
    monkeypatch.delenv("INGEST_TOKEN", raising=False)
    r = client.post("/ingest", json={"url": "https://example.com/reel/abc"})
    assert r.status_code == 202  # accepted, no header needed


def test_ingest_requires_token_when_configured(monkeypatch):
    """INGEST_TOKEN set but no header sent -> 401, and nothing is ingested."""
    monkeypatch.setenv("INGEST_TOKEN", "s3cret")
    r = client.post("/ingest", json={"url": "https://example.com/reel/abc"})
    assert r.status_code == 401


def test_ingest_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("INGEST_TOKEN", "s3cret")
    r = client.post(
        "/ingest",
        json={"url": "https://example.com/reel/abc"},
        headers={"X-Ingest-Token": "wrong"},
    )
    assert r.status_code == 401


def test_ingest_accepts_correct_token(monkeypatch):
    monkeypatch.setenv("INGEST_TOKEN", "s3cret")
    r = client.post(
        "/ingest",
        json={"url": "https://example.com/reel/abc"},
        headers={"X-Ingest-Token": "s3cret"},
    )
    assert r.status_code == 202


def test_refresh_all_gated_before_any_fetch(monkeypatch):
    """The gate must reject /refresh-all with 401 BEFORE doing the outbound fetches, so a public
    URL can't be used to hammer arXiv/Google from Katti's IP. We prove no fetch ran by making the
    first source explode if reached."""
    monkeypatch.setenv("INGEST_TOKEN", "s3cret")

    def boom(*_a, **_k):  # pragma: no cover - must never be called
        raise AssertionError("fetch ran despite a missing token")

    monkeypatch.setattr("app.main.github_radar.fetch_repos", boom)
    r = client.post("/refresh-all")
    assert r.status_code == 401


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_token_env_is_treated_as_unset(monkeypatch, blank):
    """A blank/whitespace INGEST_TOKEN counts as 'not configured' -> open, not a lockout."""
    monkeypatch.setenv("INGEST_TOKEN", blank)
    r = client.post("/ingest", json={"url": "https://example.com/reel/abc"})
    assert r.status_code == 202
