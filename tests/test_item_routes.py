"""The /item depth flow: the page opens INSTANTLY (no NIM on the click); the /analysis fragment
does the two-pass work (analyst draft -> critic refine), caches it, and is fetched async."""

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import create_engine

from app import github_radar, research, store
from app.main import app
from app.models import RadarItem


def _client(monkeypatch):
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    monkeypatch.setattr(store, "engine", eng)
    return TestClient(app)


def _seed_news(title="Tool X"):
    news = RadarItem(source="news", title=title, url="https://x", meta="m")
    store.replace_radar("news", [news])
    return store.list_radar("news")[0]


def test_item_page_opens_instantly_without_calling_nim(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(research, "analyze_item", lambda *a, **k: calls.__setitem__("n", 1))
    with _client(monkeypatch) as client:
        item = _seed_news()
        page = client.get(f"/item/{item.id}")
        assert page.status_code == 200
        assert "analyzing" in page.text  # spinner shown — page didn't wait
        assert calls["n"] == 0  # the page route never calls NIM


def test_analysis_fragment_is_two_pass_and_caches(monkeypatch):
    calls = {"draft": 0, "refine": 0}

    def draft(item, profile, client=None):
        calls["draft"] += 1
        return {"overview": "shallow", "usage": "u", "builds": ["b"], "product_ideas": ["p"]}

    def refine(item, profile, d, client=None):
        calls["refine"] += 1
        return {"overview": "DEEP read", "usage": "u2", "builds": ["B1"], "product_ideas": ["P1"]}

    monkeypatch.setattr(research, "analyze_item", draft)
    monkeypatch.setattr(research, "refine_analysis", refine)
    with _client(monkeypatch) as client:
        item = _seed_news()
        frag = client.get(f"/item/{item.id}/analysis")
        assert frag.status_code == 200
        assert "DEEP read" in frag.text and "B1" in frag.text  # the critic's deeper version wins
        assert (calls["draft"], calls["refine"]) == (1, 1)  # both passes ran

        client.get(f"/item/{item.id}/analysis")  # second fetch
        assert (calls["draft"], calls["refine"]) == (1, 1)  # cached — no re-analysis


def test_refine_falls_back_to_draft_on_critic_failure(monkeypatch):
    def draft(item, profile, client=None):
        return {"overview": "draft only", "usage": "", "builds": [], "product_ideas": []}

    def boom(*a, **k):
        raise RuntimeError("critic down")

    monkeypatch.setattr(research, "analyze_item", draft)
    monkeypatch.setattr(research, "refine_analysis", boom)
    with _client(monkeypatch) as client:
        item = _seed_news()
        frag = client.get(f"/item/{item.id}/analysis")
        assert "draft only" in frag.text  # critic failed -> the draft still shows


def test_github_item_uses_the_repo_analyzer_not_the_generic_one(monkeypatch):
    calls = {"repo": 0, "generic": 0}

    def repo(item, profile):
        calls["repo"] += 1
        return {"overview": "repo read", "usage": "u", "builds": ["b"], "product_ideas": ["p"]}

    monkeypatch.setattr(github_radar, "analyze_repo", repo)
    monkeypatch.setattr(
        research, "analyze_item", lambda *a, **k: calls.__setitem__("generic", 1)
    )
    monkeypatch.setattr(
        research, "refine_analysis", lambda item, profile, draft, client=None: draft
    )
    with _client(monkeypatch) as client:
        gh = RadarItem(source="github", title="repo X", url="u", meta="m")
        store.replace_radar("github", [gh])
        item = store.list_radar("github")[0]
        frag = client.get(f"/item/{item.id}/analysis")
        assert "repo read" in frag.text  # README-based path rendered
        assert calls == {"repo": 1, "generic": 0}  # github branch, not the generic analyzer


def test_item_detail_404_for_missing(monkeypatch):
    with _client(monkeypatch) as client:
        assert client.get("/item/99999").status_code == 404
        assert client.get("/item/99999/analysis").status_code == 404
