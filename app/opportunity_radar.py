"""Tech-radar source #7: OPPORTUNITIES — things you can actually enter, with a deadline.

Every other source answers "what exists" (repos, papers, news, discussion). This one answers
"what can I DO this month" — hackathons you can ship a project into, with a closing date and a
prize. That's the difference between input and output, so these items are ranked by URGENCY
(soonest realistic deadline first), not by popularity.

Two open, key-free JSON endpoints, both the ones the sites' own public listing pages call:
  · Devpost  — global hackathons (the big ones: AI labs, cloud vendors, YC-adjacent).
  · Unstop   — where Indian hackathons actually live (college + corporate).
Anything already closed, or closing too soon to build in, is dropped — a deadline you can't hit
is noise. Returns RadarItems (source='opps') so it shares the table, store, and feed UI."""

import json
import re
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from app.github_radar import topics_from_profile
from app.models import RadarItem

DEVPOST_URL = "https://devpost.com/api/hackathons"
UNSTOP_URL = "https://unstop.com/api/public/opportunity/search-result"
UNSTOP_ITEM_URL = "https://unstop.com/{}"
_UA = "get-your-knowledge-right/1.0 (personal knowledge radar)"

# A hackathon closing sooner than this can't be entered seriously — you can't scope, build, and
# submit inside a day. Below the floor it's noise on the desk, so it never reaches the corpus.
MIN_DAYS_LEFT = 1
_TAG_RE = re.compile(r"<[^>]+>")


class RadarError(Exception):
    """An opportunity source could not be reached or refused the request."""


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 (fixed hosts above)
            return json.loads(resp.read())
    except Exception as exc:  # noqa: BLE001 — normalize urllib/JSON errors like the other radars
        raise RadarError(f"opportunity fetch failed for {url}: {exc}") from exc


def _clean(text: str, limit: int = 260) -> str:
    """Strip HTML and collapse whitespace — Unstop returns a full HTML description."""
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", text or "")).strip()[:limit]


def _prize(raw: str) -> str:
    """Devpost wraps the prize pot in markup ('$<span ...>10,000</span>'). Strip it, and treat a
    zero pot as no prize — '🏆 $ 0' on a card is worse than saying nothing."""
    text = _clean(raw).replace(" ", "")
    return "" if not text or re.fullmatch(r"[$₹€£]?0", text) else text


def _days_from_phrase(phrase: str) -> float | None:
    """Devpost reports time left as human text ('6 days left', 'about 1 month left'). Turn that
    into days so every source ranks on one scale. Unknown shapes return None (dropped)."""
    match = re.search(r"(\d+)\s*(hour|day|week|month)", (phrase or "").lower())
    if not match:
        return None
    amount, unit = int(match.group(1)), match.group(2)
    return amount * {"hour": 1 / 24, "day": 1.0, "week": 7.0, "month": 30.0}[unit]


def _days_from_date(raw: str) -> float | None:
    """Unstop reports a real ISO end_date — days from now, or None if unparseable/past."""
    try:
        end = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    return (end - datetime.now(UTC)).total_seconds() / 86400


def _urgency(days_left: float, topic_hits: int) -> int:
    """Rank RELEVANCE first, then urgency. A hackathon in your field three weeks out beats a
    generic one closing Friday — you'd enter the first and ignore the second. Within one relevance
    tier the closer deadline wins, because that's the one you have to decide on now."""
    return max(1, int(60 - min(days_left, 60))) + 25 * topic_hits


# Words too generic to signal anything when a topic phrase is broken into parts.
_STOP = {"and", "the", "for", "with", "of", "a", "an", "on", "in", "to", "is", "new", "using"}


def _keywords(topics: list[str]) -> set[str]:
    """Broaden the profile's topic PHRASES into matchable words. Hackathon titles are short and
    branded ("Caspian AI Agent Hackathon"), so a phrase like "multi-agent systems" never appears
    verbatim and every entry would tie at zero relevance. Splitting it into {multi-agent, agent,
    systems} is what makes an AI hackathon outrank a generic one."""
    words: set[str] = set()
    for topic in topics:
        clean = topic.strip().strip(".").lower()
        if not clean:
            continue
        words.add(clean)
        for part in re.split(r"[^a-z0-9.+-]+", clean):
            if len(part) >= 2:
                words.add(part)
                # ...and split the hyphenated ones again ("multi-agent" -> "agent"), since a title
                # says "AI Agent Hackathon", never "multi-agent systems".
                words.update(bit for bit in part.split("-") if len(bit) >= 3)
    return {w for w in words if w and w not in _STOP}


def _hits(text: str, topics: list[str]) -> int:
    """How many of the user's interests this entry mentions, as WHOLE words (so "ai" matches
    "AI Agent Hackathon" but not "Vitalitics"). Capped — three matches already means "yours"."""
    low = text.lower()
    found = sum(1 for w in _keywords(topics) if re.search(rf"\b{re.escape(w)}\b", low))
    return min(found, 3)


def _devpost_queries(topics: list[str], per_source: int) -> list[str]:
    """Devpost search terms: a couple of the user's own topics plus one unfiltered sweep, so the
    list is personalized but never empty when the topics are niche."""
    picks = [t for t in topics if len(t) > 2][:3]
    queries = [
        f"{DEVPOST_URL}?{urllib.parse.urlencode({'order_by': 'deadline', 'status[]': 'open'})}"
    ]
    queries += [
        f"{DEVPOST_URL}?"
        + urllib.parse.urlencode({"order_by": "deadline", "status[]": "open", "search": p})
        for p in picks
    ]
    return queries[: max(1, per_source)]


def _from_devpost(topics: list[str], per_source: int) -> list[RadarItem]:
    items: list[RadarItem] = []
    seen: set[str] = set()
    for url in _devpost_queries(topics, per_source):
        try:
            payload = _get_json(url)
        except RadarError:
            continue  # one failed query shouldn't sink the batch (same rule as the other radars)
        for row in payload.get("hackathons", []):
            link = row.get("url")
            if not link or link in seen or row.get("invite_only"):
                continue
            days = _days_from_phrase(row.get("time_left_to_submission", ""))
            if days is None or days < MIN_DAYS_LEFT:
                continue
            seen.add(link)
            prize = _prize(row.get("prize_amount", ""))
            themes = ", ".join(t.get("name", "") for t in row.get("themes", []) if t.get("name"))
            where = (row.get("displayed_location") or {}).get("location", "")
            title = row.get("title") or "(untitled hackathon)"
            items.append(
                RadarItem(
                    source="opps",
                    title=title,
                    url=link,
                    summary=_clean(
                        f"{themes}. {row.get('registrations_count', 0)} registered · "
                        f"{row.get('submission_period_dates', '')}"
                    ),
                    meta=" · ".join(
                        part
                        for part in (
                            f"⏳ {row.get('time_left_to_submission', '')}",
                            f"🏆 {prize}" if prize else "",
                            f"📍 {where or 'online'}",
                            "Devpost",
                        )
                        if part
                    ),
                    score=_urgency(days, _hits(f"{title} {themes}", topics)),
                )
            )
    return items


def _from_unstop(topics: list[str], limit: int) -> list[RadarItem]:
    query = urllib.parse.urlencode(
        {"opportunity": "hackathons", "oppstatus": "open", "per_page": limit, "page": 1}
    )
    try:
        payload = _get_json(f"{UNSTOP_URL}?{query}")
    except RadarError:
        return []  # India feed is a bonus — never let it sink the global one
    rows = ((payload.get("data") or {}).get("data")) or []
    items: list[RadarItem] = []
    for row in rows:
        path = row.get("public_url")
        title = row.get("title")
        if not path or not title:
            continue
        days = _days_from_date(row.get("end_date"))
        if days is None or days < MIN_DAYS_LEFT:
            continue
        org = (row.get("organisation") or {}).get("name", "")
        detail = _clean(row.get("details", ""))
        items.append(
            RadarItem(
                source="opps",
                title=title,
                url=UNSTOP_ITEM_URL.format(path),
                summary=detail or None,
                meta=f"⏳ {int(days)} days left · 🏫 {org or 'Unstop'} · "
                f"📍 {row.get('region') or 'online'} · Unstop",
                score=_urgency(days, _hits(f"{title} {detail}", topics)),
            )
        )
    return items


def fetch_opportunities(
    profile: dict, topics: list[str] | None = None, per_source: int = 4, unstop_limit: int = 20
) -> list[RadarItem]:
    """Open hackathons you could still enter, soonest-deadline first, across Devpost + Unstop.
    Pass lane topics (like the other radars) so entries matching your aspects rank higher."""
    topic_list = topics or topics_from_profile(profile)
    return _from_devpost(topic_list, per_source) + _from_unstop(topic_list, unstop_limit)


def analyze_opportunity(item, profile: dict, client=None) -> dict:
    """Generate a readable, actionable summary for a hackathon — what it's actually about, what you
    could build to win, and whether it's worth your time. Uses the same {overview, usage, builds,
    product_ideas} shape as the generic analyze_item so it caches into the same RadarItem fields."""
    from app.research import _extract_json, make_llm

    client = client or make_llm()
    system = (
        "You are a hackathon strategist for ONE specific builder. You are given a hackathon title, "
        "a brief description from the listing, and the builder's focus + goals. Return STRICT JSON "
        "only with these keys: "
        "overview (80-120 words: what this hackathon is actually about — decode the theme, "
        "name the tech or problem area, explain what kind of project would win); "
        "usage (1-2 sentences: why it matters to THIS person given their focus and goals — be "
        "honest if it's not a fit); "
        "builds (array of 2-4 specific project ideas this person could submit, each with a "
        "concrete tech stack and hook that fits the theme); "
        "product_ideas (array of 1-2 ways to spin a winning submission into a portfolio piece, "
        "open-source tool, or startup pitch). "
        "Be concrete and specific. Return ONLY the JSON object."
    )
    user = (
        f"HACKATHON: {item.title}\n"
        f"Description: {item.summary or '(none)'}\n"
        f"Meta: {item.meta or '(none)'}\n"
        f"Link: {item.url}\n\n"
        f"Person's focus: {profile.get('focus', '')}\n"
        f"Goals / situation: {profile.get('goals', '')}"
    )
    return _extract_json(client.complete(system, user))
