"""Tech-radar source #6: Google News. Searches the user's focus topics via Google News' public RSS
search feed (no key, no auth). Broad coverage — it fills the lanes the dev-centric sources miss
(Web Design, Jobs, general launches). Parsed with feedparser. RadarItems (source='gnews')."""

import urllib.parse

import feedparser

from app.github_radar import topics_from_profile
from app.models import RadarItem

SEARCH = "https://news.google.com/rss/search"
_UA = "Mozilla/5.0 (get-your-knowledge-right)"


def fetch_news(
    profile: dict, per_topic: int = 4, topics: list[str] | None = None
) -> list[RadarItem]:
    """Recent news across the given topics (defaults to the profile's focus topics), de-duplicated,
    as RadarItems (source='gnews'). Pass lane topics here so the thin lanes (Web Design, Jobs) fill
    from Google News' broad coverage."""
    items: list[RadarItem] = []
    seen: set[str] = set()
    for topic in topics or topics_from_profile(profile):
        query = urllib.parse.urlencode({"q": topic, "hl": "en-US", "gl": "US", "ceid": "US:en"})
        try:
            parsed = feedparser.parse(f"{SEARCH}?{query}", agent=_UA)
        except Exception:  # noqa: BLE001 — one bad topic shouldn't sink the refresh
            continue
        for entry in parsed.entries[:per_topic]:
            link = entry.get("link")
            title = entry.get("title")
            if not link or not title or link in seen:
                continue
            seen.add(link)
            src = entry.get("source")
            publisher = src.get("title") if isinstance(src, dict) else None
            items.append(
                RadarItem(
                    source="gnews",
                    title=title,
                    url=link,
                    summary=None,  # Google News summaries are just publisher boilerplate
                    meta=f"🔎 {publisher}" if publisher else "🔎 Google News",
                    score=0,
                )
            )
    return items
