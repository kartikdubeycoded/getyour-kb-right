from app import github_radar


def test_topics_from_profile_splits_focus():
    p = {"focus": "AI engineering, data science, RAG"}
    assert github_radar.topics_from_profile(p) == ["AI engineering", "data science", "RAG"]


def test_topics_explicit_radar_topics_override():
    p = {"focus": "ignored", "radar_topics": ["multi-agent", "llm"]}
    assert github_radar.topics_from_profile(p) == ["multi-agent", "llm"]


def test_topics_fallback_when_empty():
    assert github_radar.topics_from_profile({}) == ["machine learning"]


def test_fetch_repos_builds_items_and_dedupes(monkeypatch):
    repo = {
        "full_name": "owner/repo",
        "html_url": "https://github.com/owner/repo",
        "description": "a useful tool",
        "stargazers_count": 1234,
        "language": "Python",
    }
    # two topics both return the same repo -> must dedupe to one
    monkeypatch.setattr(github_radar, "_search", lambda topic, per_topic, token: [repo])
    items = github_radar.fetch_repos({"focus": "AI, ML"}, token=None)

    assert len(items) == 1
    item = items[0]
    assert item.source == "github"
    assert item.title == "owner/repo"
    assert item.url == "https://github.com/owner/repo"
    assert item.score == 1234
    assert "Python" in item.meta and "1,234" in item.meta


def test_fetch_repos_searches_the_given_topics_not_just_focus(monkeypatch):
    searched: list[str] = []

    def fake_search(topic, per_topic, token):
        searched.append(topic)
        return [{"full_name": f"o/{topic}", "html_url": f"https://github.com/o/{topic}"}]

    monkeypatch.setattr(github_radar, "_search", fake_search)
    items = github_radar.fetch_repos({"focus": "AI, ML"}, topics=["web design", "jobs"])

    assert searched == ["web design", "jobs"]  # lane topics drive the search, not the focus line
    assert {i.title for i in items} == {"o/web design", "o/jobs"}


def test_fetch_repos_skips_a_rate_limited_topic(monkeypatch):
    def flaky(topic, per_topic, token):
        if topic == "bad":
            raise github_radar.RadarError("429")
        return [{"full_name": "o/good", "html_url": "https://github.com/o/good"}]

    monkeypatch.setattr(github_radar, "_search", flaky)
    items = github_radar.fetch_repos({}, topics=["bad", "good"])

    assert [i.title for i in items] == ["o/good"]  # the failed topic drops; the batch survives


def test_fetch_repos_caps_topics_to_the_unauth_rate_limit(monkeypatch):
    # GitHub Search allows ~10 req/min unauthenticated; one request per topic. fetch_repos must cap
    # so a SYNC completes instead of 429-ing the tail topics (dropping them shrinks the corpus).
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)  # force the unauthenticated path
    searched: list[str] = []
    monkeypatch.setattr(
        github_radar, "_search", lambda topic, per_topic, token: searched.append(topic) or []
    )
    github_radar.fetch_repos({}, topics=[f"t{i}" for i in range(12)])
    assert searched == [f"t{i}" for i in range(10)]  # only the first 10 searched, not all 12


def test_fetch_repos_allows_more_topics_with_a_token(monkeypatch):
    searched: list[str] = []
    monkeypatch.setattr(
        github_radar, "_search", lambda topic, per_topic, token: searched.append(topic) or []
    )
    topics = [f"t{i}" for i in range(12)]
    github_radar.fetch_repos({}, token="ghp_x", topics=topics)
    assert searched == topics  # a token raises the limit (~30/min) — all 12 go through


def test_analyze_repo_parses_breakdown(monkeypatch):
    from app.models import RadarItem

    monkeypatch.setattr(github_radar, "fetch_readme", lambda *a, **k: "some readme")

    class FakeClient:
        def complete(self, system, user):
            return '{"overview":"o","usage":"u","builds":["b1","b2"],"product_ideas":["p1"]}'

    item = RadarItem(source="github", title="o/r", url="https://github.com/o/r", summary="d")
    data = github_radar.analyze_repo(item, {"focus": "AI"}, client=FakeClient())
    assert data["overview"] == "o"
    assert data["builds"] == ["b1", "b2"]
    assert data["product_ideas"] == ["p1"]
