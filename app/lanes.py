"""The curation layer: organize the whole radar corpus into the user's own aspects ("lanes") —
Web Design, AI/ML, News, etc. A lane is just a name + topic words; every stored radar item
(GitHub, HN, Reddit, News) is scored against those words, so one lane MIXES all sources and shows
the items that matter to THIS person for THAT aspect. Lanes live in profile.yaml and reuse the
existing corpus — no new fetchers, no new tables."""

import re

from app.github_radar import topics_from_profile
from app.models import RadarItem


def _named_topic_lists(raw: object) -> list[tuple[str, list[str]]]:
    """Parse a list of {name, topics} entries into (name, topics) tuples, dropping any that are
    malformed or have no topics. Shared by projects AND aspect-lanes — both are just named bags of
    topic words, so they parse identically."""
    out: list[tuple[str, list[str]]] = []
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            topics = [str(t).strip() for t in (entry.get("topics") or []) if str(t).strip()]
            if name and topics:
                out.append((name, topics))
    return out


def projects_from_profile(profile: dict) -> list[tuple[str, list[str]]]:
    """The user's ACTUAL running builds (profile.projects: [{name, about?, topics}]). Each becomes a
    top-priority lane so the radar surfaces items useful to what he's building RIGHT NOW (Jay, the
    portfolio, this app) — not just generic aspect keywords. Empty when no projects are declared."""
    return _named_topic_lists(profile.get("projects"))


def lanes_from_profile(profile: dict) -> list[tuple[str, list[str]]]:
    """Every curated view, projects FIRST then aspects: profile.projects (his real builds) ahead of
    profile.lanes (generic aspects like AI/ML, Web Design). Projects lead so items about what he's
    building rank above generic interest everywhere downstream (home, /lanes, /lane, and the fetch
    set). Falls back to a single 'All' lane from the focus line so the page is never empty."""
    lanes = projects_from_profile(profile) + _named_topic_lists(profile.get("lanes"))
    return lanes or [("All", topics_from_profile(profile))]


def search_topics(profile: dict, limit: int = 18) -> list[str]:
    """Every topic worth fetching: the focus-line topics, then PROJECT topics (his real builds),
    then aspect-lane topics — deduped (case-insensitive, first spelling wins) and capped. Projects
    come before generic aspects so the sources actively pull items about what he's building now, not
    just his broad interests. The broad sources (Google News, arXiv) search THIS instead of just the
    focus line, so the thin lanes (Web Design, Jobs) and the projects all fill instead of staying
    empty."""
    out: list[str] = []
    seen: set[str] = set()

    def _add(topic: str) -> None:
        key = topic.lower()
        if topic and key not in seen:
            seen.add(key)
            out.append(topic)

    for topic in topics_from_profile(profile):
        _add(topic)
    for _name, topics in lanes_from_profile(profile):
        for topic in topics:
            _add(topic)
    return out[:limit]


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


def pulse(items: list[RadarItem], profile: dict, top: int = 10) -> list[dict]:
    """The cross-lane PULSE: what's hottest across your WHOLE spectrum right now. Runs the signal
    computation over the union of every lane's topics (search_topics), so one glance shows where
    tech is moving in the aspects you care about — ranked by source-spread, then volume."""
    return lane_signal(items, search_topics(profile), top=top)


def search_corpus(items: list[RadarItem], query: str, limit: int = 50) -> list[RadarItem]:
    """Free-text search across the WHOLE radar corpus, every source at once. Splits the query into
    terms and ranks each item by weighted matches — a hit in the TITLE counts more than one in the
    summary/meta — so the most on-topic items float up. Case-insensitive substring match (typing
    'diffus' finds 'diffusion'). Items matching no term drop out. (v1 is keyword-relevance; the
    ranker is the seam where embeddings/semantic search swap in later.)"""
    terms = [t for t in re.split(r"\s+", query.strip().lower()) if t]
    if not terms:
        return []
    scored: list[tuple[int, RadarItem]] = []
    for item in items:
        title = (item.title or "").lower()
        body = f"{item.summary or ''} {item.meta or ''}".lower()
        score = sum((3 if term in title else 1 if term in body else 0) for term in terms)
        if score:
            scored.append((score, item))
    scored.sort(key=lambda pair: (pair[0], pair[1].id or 0), reverse=True)
    return [item for _score, item in scored[:limit]]


def lane_signal(items: list[RadarItem], topics: list[str], top: int = 5) -> list[dict]:
    """What's heating up in a lane RIGHT NOW: for each of the lane's topics, how many corpus items
    mention it (mentions) and across how many DISTINCT sources (sources). A topic echoed by
    github + hn + news + arxiv is a stronger signal than one source shouting, so we rank by
    source-spread first, then raw volume. Topics with zero mentions drop out. This is the
    intelligence layer: reads the corpus the lanes already curate — no new fetch, no new table."""
    rows: list[dict] = []
    for topic in topics:
        term = topic.lower()
        sources: set[str] = set()
        mentions = 0
        for item in items:
            text = f"{item.title} {item.summary or ''} {item.meta or ''}".lower()
            if _matches(text, term):
                mentions += 1
                sources.add(item.source)
        if mentions:
            rows.append({"topic": topic, "mentions": mentions, "sources": len(sources)})
    rows.sort(key=lambda r: (r["sources"], r["mentions"]), reverse=True)
    return rows[:top]


def curate(
    items: list[RadarItem], topics: list[str], limit: int = 30, avoid: list[str] = ()
) -> list[RadarItem]:
    """The items matching a lane's topics, best match first (ties broken by newest = highest id),
    with any item hitting an avoid word filtered out."""
    hits = [(score_item(i, topics, avoid), i) for i in items]
    hits = [(s, i) for s, i in hits if s > 0]
    hits.sort(key=lambda pair: (pair[0], pair[1].id or 0), reverse=True)
    return [i for _s, i in hits[:limit]]
