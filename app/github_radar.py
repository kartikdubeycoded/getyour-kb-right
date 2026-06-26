"""Tech-radar source #1: GitHub. Pulls the most-starred recently-active repos for the user's focus
topics via GitHub's official Search API (free; an optional GITHUB_TOKEN raises the rate limit). No
scraping — this is the documented public API. Returns RadarItems ready to store."""

import json
import os
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

from app.models import RadarItem

SEARCH_URL = "https://api.github.com/search/repositories"
README_URL = "https://api.github.com/repos/{}/readme"
_UA = "get-your-knowledge-right"


class RadarError(Exception):
    """The GitHub API could not be reached or refused the request (rate limit, network)."""


def topics_from_profile(profile: dict, limit: int = 6) -> list[str]:
    """Search topics: explicit profile.radar_topics if set, else split the focus line on commas."""
    explicit = profile.get("radar_topics")
    if isinstance(explicit, list) and explicit:
        return [str(t).strip() for t in explicit if str(t).strip()][:limit]
    focus = (profile.get("focus") or "").replace("\n", " ")
    terms = [t.strip() for t in focus.split(",") if t.strip()]
    return terms[:limit] or ["machine learning"]


def _search(topic: str, per_topic: int, token: str | None) -> list[dict]:
    since = (datetime.now(UTC) - timedelta(days=365)).strftime("%Y-%m-%d")
    query = urllib.parse.urlencode(
        {"q": f"{topic} pushed:>{since}", "sort": "stars", "order": "desc", "per_page": per_topic}
    )
    req = urllib.request.Request(f"{SEARCH_URL}?{query}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", _UA)  # GitHub rejects requests with no User-Agent
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 (fixed api.github.com)
            return json.loads(resp.read()).get("items", [])
    except Exception as exc:  # noqa: BLE001 — normalize urllib/JSON errors
        raise RadarError(f"GitHub search failed for '{topic}': {exc}") from exc


def fetch_readme(full_name: str, token: str | None = None, max_chars: int = 3500) -> str:
    """The repo's README as raw text (truncated), or "" if it can't be fetched. Best-effort."""
    token = token or os.getenv("GITHUB_TOKEN")
    req = urllib.request.Request(README_URL.format(full_name))
    req.add_header("Accept", "application/vnd.github.raw")  # raw text, not base64
    req.add_header("User-Agent", _UA)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 (fixed api.github.com)
            return resp.read().decode("utf-8", "replace")[:max_chars]
    except Exception:  # noqa: BLE001 — README is optional context
        return ""


def analyze_repo(item: RadarItem, profile: dict, client=None, token: str | None = None) -> dict:
    """AI breakdown of a repo FOR this person: overview, usage, builds, product ideas. Returns a
    dict with those keys (lists for builds/product_ideas)."""
    from app.research import NvidiaNimClient, _extract_json

    client = client or NvidiaNimClient()
    readme = fetch_readme(item.title, token)
    system = (
        "You explain a GitHub repo to a specific builder and return STRICT JSON only. Keys: "
        "overview (2-3 plain sentences: what it is and why it matters); "
        "usage (2-3 sentences: how they'd actually use/run it); "
        "builds (array of 3-4 concrete things THIS person could build USING this repo, tied to "
        "their focus and goals); "
        "product_ideas (array of 2-3 product or monetizable ideas built on it — freelance offer, "
        "paid tool, service). Be concrete and practical. Return ONLY the JSON object."
    )
    user = (
        f"Repo: {item.title}\n"
        f"Description: {item.summary or '(none)'}\n"
        f"Person's focus: {profile.get('focus', '')}\n"
        f"Goals / situation: {profile.get('goals', '')}\n\n"
        f"README (truncated):\n{readme or '(unavailable)'}"
    )
    return _extract_json(client.complete(system, user))


def fetch_repos(
    profile: dict, per_topic: int = 4, token: str | None = None, topics: list[str] | None = None
) -> list[RadarItem]:
    """Top repos across the given topics (defaults to the profile's focus topics), de-duplicated,
    as RadarItems (source='github'). Pass lane topics so the thin lanes (Web Design, Jobs) fill with
    repos too — not just the focus line. Per-topic resilient: a rate-limited topic (GitHub Search
    allows ~10 unauthenticated req/min) is skipped, so it never sinks the whole batch."""
    token = token or os.getenv("GITHUB_TOKEN")
    items: list[RadarItem] = []
    seen: set[str] = set()
    for topic in topics or topics_from_profile(profile):
        try:
            repos = _search(topic, per_topic, token)
        except RadarError:
            continue  # one failed/rate-limited topic shouldn't sink the whole refresh
        for repo in repos:
            url = repo.get("html_url")
            if not url or url in seen:
                continue
            seen.add(url)
            stars = int(repo.get("stargazers_count") or 0)
            lang = repo.get("language") or "—"
            items.append(
                RadarItem(
                    source="github",
                    title=repo.get("full_name") or url,
                    url=url,
                    summary=repo.get("description"),
                    meta=f"⭐ {stars:,} · {lang}",
                    score=stars,
                )
            )
    return items
