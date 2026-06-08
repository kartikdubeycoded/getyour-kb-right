"""Tech-radar source #5: arXiv. Pulls recent papers matching the user's focus topics via the
official arXiv API (export.arxiv.org — open, no key, no captcha). The API returns an Atom feed, so
we parse it with feedparser, just like the RSS source. Returns RadarItems (source='arxiv'), so they
share the table, store, and lane curation."""

import re
import urllib.parse

import feedparser

from app.github_radar import topics_from_profile
from app.models import RadarItem

API = "https://export.arxiv.org/api/query"
ABSTRACT_LIMIT = 280
_UA = "get-your-knowledge-right"


def _clean(text: str, limit: int) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()[:limit]


def fetch_papers(
    profile: dict, max_results: int = 20, topics: list[str] | None = None
) -> list[RadarItem]:
    """Most-recent papers across the given topics (defaults to the profile's focus topics),
    de-duplicated (source='arxiv'). All topics go in ONE `OR` query — arXiv rate-limits bursts
    (HTTP 429), so we ask it a single time. Pass lane topics here to fill the thin lanes."""
    topics = topics or topics_from_profile(profile)
    if not topics:
        return []
    search = " OR ".join(f"all:{topic}" for topic in topics)
    query = urllib.parse.urlencode(
        {
            "search_query": search,
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
    )
    try:
        parsed = feedparser.parse(f"{API}?{query}", agent=_UA)
    except Exception:  # noqa: BLE001 — network/parse failure shouldn't break refresh-all
        return []
    items: list[RadarItem] = []
    seen: set[str] = set()
    for entry in parsed.entries:
        link = entry.get("link")
        title = _clean(entry.get("title", ""), 200)
        if not link or not title or link in seen:
            continue
        seen.add(link)
        authors = ", ".join(a.get("name", "") for a in (entry.get("authors") or [])[:3])
        items.append(
            RadarItem(
                source="arxiv",
                title=title,
                url=link,
                summary=_clean(entry.get("summary", ""), ABSTRACT_LIMIT) or None,
                meta=f"📄 {authors}" if authors else "📄 arXiv",
                score=0,
            )
        )
    return items
