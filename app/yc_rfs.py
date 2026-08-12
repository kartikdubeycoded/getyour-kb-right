"""Tech-radar source: YC Requests for Startups (RFS).

The RSS feed already surfaces what YC *writes about* (app/rss_radar.py). This source answers the
stronger question: what does YC actually want built NEXT? Each RFS is a partner naming a specific
gap and asking founders to fill it — a signal that comes with a cheque attached, not just an
opinion. That's the difference between "what exists" and "what's being funded".

The page is server-rendered HTML (no key, no API — the same ToS-safe situation as the other
radars), so we parse the fixed markup and turn each request into a RadarItem under its OWN
source='ycrfs'. Separate from 'news' so a YC page redesign can never wipe the whole news corpus,
the same reasoning that keeps 'trending' apart from 'github'. Items are scored by topic match
(reusing the opportunity radar's keyword scheme, not a third one) so a request in your field
floats to the top."""

import html
import re
import urllib.request

from app.github_radar import topics_from_profile
from app.models import RadarItem
from app.opportunity_radar import _hits  # reuse the shared topic-match scoring — no third scheme

RFS_URL = "https://www.ycombinator.com/rfs"
_UA = "get-your-knowledge-right/1.0 (personal knowledge radar)"

# The page wraps each request in <div id="SLUG"> (a kebab-case anchor, e.g. "multiplayer-ai").
# Everything between one such div and the next is that request's block, so split on the anchors
# instead of trying to balance the nested divs inside each one.
_ENTRY_RE = re.compile(r'<div id="([a-z0-9][a-z0-9-]*)">')
# The h3 carries a trailing "#" copy-link anchor as chrome — the title is the text before it.
_H3_RE = re.compile(r"<h3[^>]*>(.*?)</h3>", re.S)
# The author is the first <a> after "By<!-- -->". Comments <!-- --> are rendered INSIDE the name
# ("Aaron<!-- --> <!-- -->Epstein"), so they must be stripped before joining or the name welds
# together into "AaronEpstein".
_AUTHOR_RE = re.compile(r"By\s*<!--\s*-->\s*<a[^>]*>(.*?)</a>", re.S)
_BODY_RE = re.compile(r'<div class="whitespace-pre-wrap[^"]*"[^>]*>(.*?)</div>', re.S)
# The first page-level <h2> is the batch label ("Fall 2026"). The footer's h2 comes later, so a
# first-match search lands on the batch, not the footer.
_BATCH_RE = re.compile(r"<h2[^>]*>(.*?)</h2>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


class RadarError(Exception):
    """The YC RFS page could not be reached or refused the request."""


def _get_html(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 (fixed host above)
            return resp.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 — normalize urllib/network errors like the other radars
        raise RadarError(f"yc rfs fetch failed for {url}: {exc}") from exc


def _clean(text: str) -> str:
    """Strip HTML tags and <!-- --> comments, unescape entities, collapse whitespace. The body is
    prose with &#x27; / &quot; escapes, so this yields the plain text shown on the card."""
    text = _COMMENT_RE.sub("", text or "")
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _title(chunk: str) -> str:
    """The h3 text minus its trailing '#' anchor. The anchor is a copy-link affordance, not part of
    the request's name, and left in it would show 'Multiplayer AI#' on the card."""
    match = _H3_RE.search(chunk)
    if not match:
        return ""
    title = _clean(match.group(1))
    return title[:-1].strip() if title.endswith("#") else title


def _author(chunk: str) -> str:
    """The YC partner who wrote the request, from the first <a> after 'By'. Stripping the HTML
    comments first is what turns 'Aaron<!-- --> <!-- -->Epstein' into 'Aaron Epstein'."""
    match = _AUTHOR_RE.search(chunk)
    return _clean(match.group(1)) if match else ""


def _parse(page: str, topics: list[str]) -> list[RadarItem]:
    batch_match = _BATCH_RE.search(page)
    batch = _clean(batch_match.group(1)) if batch_match else ""
    starts = [(m.start(), m.group(1)) for m in _ENTRY_RE.finditer(page)]
    items: list[RadarItem] = []
    for i, (start, slug) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(page)
        chunk = page[start:end]
        title = _title(chunk)
        if not title or title == "The Primer":
            continue  # the intro essay is context, not a request to build
        body_match = _BODY_RE.search(chunk)
        body = _clean(body_match.group(1)) if body_match else ""
        partner = _author(chunk)
        items.append(
            RadarItem(
                source="ycrfs",
                title=title,
                url=f"{RFS_URL}#{slug}",
                summary=body[:400] or None,
                meta=" · ".join(
                    part for part in ("YC RFS", batch, f"by {partner}" if partner else "") if part
                ),
                # Higher = matches more of the user's topics; no deadline here, so relevance IS the
                # rank. The page states no date, so we never fabricate one — published_at is None.
                score=_hits(f"{title} {body}", topics),
            )
        )
    return items


def fetch_yc_rfs(profile: dict, topics: list[str] | None = None) -> list[RadarItem]:
    """YC's current Requests for Startups, as RadarItems (source='ycrfs'), ranked by topic match.
    Pass lane topics (like the other radars) so a request matching your aspects ranks higher. One
    failed fetch returns [] instead of raising — a YC outage must never crash a refresh."""
    topic_list = topics or topics_from_profile(profile)
    try:
        page = _get_html(RFS_URL)
    except RadarError:
        return []  # a single dead source never sinks the batch (same rule as _from_unstop)
    return _parse(page, topic_list)
