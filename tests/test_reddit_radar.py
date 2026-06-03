import pytest

from app import reddit_radar


def test_has_credentials_reflects_env(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    assert reddit_radar.has_credentials() is False
    monkeypatch.setenv("REDDIT_CLIENT_ID", "x")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "y")
    assert reddit_radar.has_credentials() is True


def test_subreddits_explicit_override_and_strip_prefix():
    p = {"radar_subreddits": ["r/MachineLearning", "LocalLLaMA"]}
    assert reddit_radar.subreddits_from_profile(p) == ["MachineLearning", "LocalLLaMA"]


def test_subreddits_fallback_to_defaults():
    assert reddit_radar.subreddits_from_profile({}) == reddit_radar._DEFAULT_SUBS[:6]


def test_get_token_raises_without_creds(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    with pytest.raises(reddit_radar.RadarError):
        reddit_radar._get_token()


def test_fetch_posts_builds_items_and_dedupes(monkeypatch):
    monkeypatch.setattr(reddit_radar, "_get_token", lambda: "tok")
    post = {
        "title": "Big new model dropped",
        "permalink": "/r/LocalLLaMA/comments/abc/big/",
        "ups": 2500,
        "subreddit": "LocalLLaMA",
        "selftext": "details here",
    }
    # every subreddit returns the same post -> must dedupe by permalink to one
    monkeypatch.setattr(reddit_radar, "_fetch_sub", lambda sub, per_sub, token: [post])
    items = reddit_radar.fetch_posts({"radar_subreddits": ["LocalLLaMA", "MachineLearning"]})

    assert len(items) == 1
    item = items[0]
    assert item.source == "reddit"
    assert item.title == "Big new model dropped"
    assert item.url == "https://www.reddit.com/r/LocalLLaMA/comments/abc/big/"
    assert item.score == 2500
    assert "r/LocalLLaMA" in item.meta and "2,500" in item.meta


def test_fetch_posts_skips_failing_subreddit(monkeypatch):
    monkeypatch.setattr(reddit_radar, "_get_token", lambda: "tok")

    def maybe_boom(sub, per_sub, token):
        if sub == "bad":
            raise reddit_radar.RadarError("rate limited")
        return [{"title": "ok", "permalink": "/r/good/1/", "ups": 5, "subreddit": "good"}]

    monkeypatch.setattr(reddit_radar, "_fetch_sub", maybe_boom)
    items = reddit_radar.fetch_posts({"radar_subreddits": ["bad", "good"]})
    assert [i.title for i in items] == ["ok"]  # bad sub skipped, good one kept
