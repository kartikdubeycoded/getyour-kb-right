"""Tech-radar source #2: Hacker News. Pulls top stories matching the user's focus topics via the
official HN Search API (hn.algolia.com — fully open, no auth, no key, no captcha). Returns
RadarItems in the same shape as the GitHub radar, so they share the table, store, and feed UI."""

import json
import urllib.parse
import urllib.request

from app.github_radar import topics_from_profile  # same "topics from focus line" logic
from app.models import RadarItem

SEARCH_URL = "https://hn.algolia.com/api/v1/search"  # by relevance+popularity
ITEM_URL = "https://news.ycombinator.com/item?id={}"
_UA = "get-your-knowledge-right"


class RadarError(Exception):
    """The HN Search API could not be reached or refused the request."""


def _search(topic: str, hits: int) -> list[dict]:
    query = urllib.parse.urlencode({"query": topic, "tags": "story", "hitsPerPage": hits})
    req = urllib.request.Request(f"{SEARCH_URL}?{query}")
    req.add_header("User-Agent", _UA)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 (fixed hn.algolia.com)
            return json.loads(resp.read()).get("hits", [])
    except Exception as exc:  # noqa: BLE001 — normalize urllib/JSON errors
        raise RadarError(f"HN search failed for '{topic}': {exc}") from exc


def fetch_stories(
    profile: dict, per_topic: int = 5, topics: list[str] | None = None
) -> list[RadarItem]:
    """Top HN stories across the given topics (defaults to the profile's focus topics),
    de-duplicated, as RadarItems (source='hn'). Pass lane topics so the thin lanes (Web Design,
    Jobs) fill with discussions too — not just the focus line."""
    items: list[RadarItem] = []
    seen: set[str] = set()
    for topic in topics or topics_from_profile(profile):
        try:
            hits = _search(topic, per_topic)
        except RadarError:
            continue  # one failed topic shouldn't sink the whole refresh
        for hit in hits:
            obj_id = hit.get("objectID")
            if not obj_id or obj_id in seen:
                continue
            seen.add(obj_id)
            points = int(hit.get("points") or 0)
            comments = int(hit.get("num_comments") or 0)
            discuss = ITEM_URL.format(obj_id)
            items.append(
                RadarItem(
                    source="hn",
                    title=hit.get("title") or "(untitled)",
                    url=hit.get("url") or discuss,  # the story link, else the HN thread
                    summary=f"💬 {comments} comments · discuss: {discuss}",
                    meta=f"▲ {points:,} points",
                    score=points,
                )
            )
    return items
