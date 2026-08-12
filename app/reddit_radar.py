"""Tech-radar source: Reddit, via the OFFICIAL OAuth API (app-only, read-only). ToS-safe — the
documented API, no scraping, no UA-spoofing to defeat bot-blocks. Needs a free registered app:
REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET in .env. Uses the confidential-client 'client_credentials'
grant, so NO username/password — just the app's id + secret.

Dormant until creds are set: has_credentials() is False and the tab shows a setup hint instead of
erroring. Returns RadarItems in the shared shape (same table/store/feed UI as GitHub + HN)."""

import base64
import json
import os
import urllib.parse
import urllib.request

from app import freshness
from app.models import RadarItem

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
LISTING_URL = "https://oauth.reddit.com/r/{sub}/top?t=week&limit={limit}"
# Reddit requires a unique descriptive UA; generic ones get rate-limited harder.
_UA = "get-your-knowledge-right/0.1 (personal knowledge radar)"

_DEFAULT_SUBS = ["MachineLearning", "LocalLLaMA", "datascience", "Python", "artificial"]


class RadarError(Exception):
    """Reddit auth/fetch failed (missing creds, bad creds, rate limit, network)."""


def has_credentials() -> bool:
    """True once the free app's id + secret are in the environment."""
    return bool(os.getenv("REDDIT_CLIENT_ID") and os.getenv("REDDIT_CLIENT_SECRET"))


def subreddits_from_profile(profile: dict, limit: int = 6) -> list[str]:
    """Subreddits to scan: explicit profile.radar_subreddits if set, else a sensible default."""
    explicit = profile.get("radar_subreddits")
    if isinstance(explicit, list) and explicit:
        return [str(s).strip().lstrip("r/") for s in explicit if str(s).strip()][:limit]
    return _DEFAULT_SUBS[:limit]


def _get_token() -> str:
    """Exchange the app's id+secret for a short-lived read-only bearer token (app-only OAuth)."""
    cid, secret = os.getenv("REDDIT_CLIENT_ID"), os.getenv("REDDIT_CLIENT_SECRET")
    if not (cid and secret):
        raise RadarError("REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not set (register a free app)")
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST")  # noqa: S310 (fixed reddit.com)
    req.add_header("User-Agent", _UA)
    basic = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    req.add_header("Authorization", f"Basic {basic}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 (fixed reddit.com)
            token = json.loads(resp.read()).get("access_token")
    except Exception as exc:  # noqa: BLE001 — normalize urllib/JSON errors
        raise RadarError(f"Reddit token request failed: {exc}") from exc
    if not token:
        raise RadarError("Reddit returned no access_token (check the client id/secret)")
    return token


def _fetch_sub(sub: str, limit: int, token: str) -> list[dict]:
    req = urllib.request.Request(LISTING_URL.format(sub=sub, limit=limit))
    req.add_header("User-Agent", _UA)
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 (fixed reddit.com)
            children = json.loads(resp.read()).get("data", {}).get("children", [])
        return [c.get("data", {}) for c in children]
    except Exception as exc:  # noqa: BLE001 — normalize urllib/JSON errors
        raise RadarError(f"Reddit fetch failed for r/{sub}: {exc}") from exc


def fetch_posts(profile: dict, per_sub: int = 6) -> list[RadarItem]:
    """Top posts of the week across the profile's subreddits, de-duplicated, as RadarItems."""
    token = _get_token()  # raises RadarError if creds are missing/bad
    items: list[RadarItem] = []
    seen: set[str] = set()
    for sub in subreddits_from_profile(profile):
        try:
            posts = _fetch_sub(sub, per_sub, token)
        except RadarError:
            continue  # one bad subreddit shouldn't sink the whole refresh
        for post in posts:
            permalink = post.get("permalink")
            if not permalink or permalink in seen:
                continue
            seen.add(permalink)
            ups = int(post.get("ups") or 0)
            body = (post.get("selftext") or "").strip()
            items.append(
                RadarItem(
                    source="reddit",
                    title=post.get("title") or "(untitled)",
                    url=f"https://www.reddit.com{permalink}",
                    summary=body[:280] or post.get("url"),  # self-text excerpt, else the linked URL
                    meta=f"⬆ {ups:,} · r/{post.get('subreddit', sub)}",
                    score=ups,
                    published_at=freshness.from_epoch(post.get("created_utc")),
                )
            )
    return items
