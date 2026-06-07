"""The curation layer: organize the whole radar corpus into the user's own aspects ("lanes") —
Web Design, AI/ML, News, etc. A lane is just a name + topic words; every stored radar item
(GitHub, HN, Reddit, News) is scored against those words, so one lane MIXES all sources and shows
the items that matter to THIS person for THAT aspect. Lanes live in profile.yaml and reuse the
existing corpus — no new fetchers, no new tables."""

import re

from app.github_radar import topics_from_profile
from app.models import RadarItem


def lanes_from_profile(profile: dict) -> list[tuple[str, list[str]]]:
    """The user's aspects: profile.lanes (list of {name, topics}) if set, else a single 'All' lane
    built from the focus line so the page is never empty."""
    raw = profile.get("lanes")
    lanes: list[tuple[str, list[str]]] = []
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            topics = [str(t).strip() for t in (entry.get("topics") or []) if str(t).strip()]
            if name and topics:
                lanes.append((name, topics))
    return lanes or [("All", topics_from_profile(profile))]


def avoid_terms(profile: dict) -> list[str]:
    """Words that should knock an item out of every lane — from profile.avoid_topics (a crisp list
    of keywords like crypto / NFT / gambling). Personalization: the user's dislikes, made real."""
    raw = profile.get("avoid_topics")
    if isinstance(raw, list):
        return [str(t).strip().lower() for t in raw if str(t).strip()]
    return []


def _matches(text: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def score_item(item: RadarItem, topics: list[str], avoid: list[str] = ()) -> int:
    """How many of the lane's topics this item mentions, matched as WHOLE words (so "UI" doesn't
    match inside "building" and "agent" doesn't match inside "VoltAgent"). Searches title +
    summary + meta. Returns 0 if the item hits any avoid word, so disliked topics drop out."""
    text = f"{item.title} {item.summary or ''} {item.meta or ''}".lower()
    if any(_matches(text, a) for a in avoid):
        return 0
    return sum(1 for t in topics if _matches(text, t.lower()))


def curate(
    items: list[RadarItem], topics: list[str], limit: int = 30, avoid: list[str] = ()
) -> list[RadarItem]:
    """The items matching a lane's topics, best match first (ties broken by newest = highest id),
    with any item hitting an avoid word filtered out."""
    hits = [(score_item(i, topics, avoid), i) for i in items]
    hits = [(s, i) for s, i in hits if s > 0]
    hits.sort(key=lambda pair: (pair[0], pair[1].id or 0), reverse=True)
    return [i for _s, i in hits[:limit]]
