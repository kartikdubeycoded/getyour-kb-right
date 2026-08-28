"""When a radar item was actually published.

Every source reports time in a different shape: feedparser hands back a `struct_time` (news, gnews,
arxiv, github-trending), Algolia and Reddit use unix epochs, GitHub's Search API uses ISO-8601
strings. Each helper below normalizes ONE of those shapes into an aware UTC datetime.

Two rules hold everywhere:

* **A bad value returns None, never a guess.** `published_at` decides what sits at the top of the
  feed, so a wrong timestamp is worse than no timestamp — it would pin a stale item above today's
  news. Unparseable input degrades to None and the item sorts by insert order like it does today.
* **Everything is UTC-aware.** Naive datetimes get UTC attached rather than being left ambiguous,
  because comparing naive and aware datetimes raises at sort time.
"""

import calendar
from datetime import UTC, datetime

# A feed that reports a date far in the future would otherwise own the top of the page forever.
# Publishers do get this wrong (bad timezone math, scheduled posts), so anything beyond this many
# days ahead is treated as untrustworthy and dropped back to None.
_MAX_FUTURE_DAYS = 2


def _sane(moment: datetime | None) -> datetime | None:
    """Reject timestamps we can't trust: absurdly old (epoch-zero placeholders) or in the future."""
    if moment is None:
        return None
    now = datetime.now(UTC)
    if moment.year < 1990 or (moment - now).days > _MAX_FUTURE_DAYS:
        return None
    return moment


def from_struct_time(parsed) -> datetime | None:
    """feedparser's `published_parsed` / `updated_parsed`.

    Note `calendar.timegm`, not `time.mktime`: feedparser normalizes every feed's date to UTC, but
    `mktime` interprets a struct_time as LOCAL time — which would shift every news item by the
    machine's offset (5.5h here) and quietly mis-order the feed against sources that use epochs.
    """
    if not parsed:
        return None
    try:
        return _sane(datetime.fromtimestamp(calendar.timegm(parsed), tz=UTC))
    except (TypeError, ValueError, OverflowError):
        return None


def from_epoch(value) -> datetime | None:
    """Unix seconds — Algolia's `created_at_i` (HN), Reddit's `created_utc`."""
    if value in (None, "", 0):
        return None
    try:
        return _sane(datetime.fromtimestamp(float(value), tz=UTC))
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def from_iso(raw) -> datetime | None:
    """ISO-8601 strings — GitHub's `pushed_at` ("2026-07-30T12:00:00Z"), arXiv's `published`.
    Python's parser rejects a trailing "Z" before 3.11-era builds and on some shapes, so normalize
    it to an explicit +00:00 offset first."""
    if not raw:
        return None
    text = str(raw).strip()
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return _sane(moment.astimezone(UTC))


# ---- reading a timestamp back out (the clock the UI and the heartbeat share) ----
#
# Everything above turns a source's date INTO a UTC datetime. Everything below turns one back into
# something a human reads. Both live here so the project has exactly one clock: if the app and the
# scheduler ever disagreed about "how old is this", the header would contradict the feed.


def aware(moment) -> datetime | None:
    """SQLite hands datetimes back naive. Comparing naive against aware raises, so attach UTC —
    which is what they were stored as.

    Anything that is not a datetime — None, or a Jinja Undefined from a row type that has no date
    column — degrades to None. These are template globals: a missing attribute must render as "no
    date", never as a 500 on the page.
    """
    if not isinstance(moment, datetime):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def humanize(delta_seconds: float) -> str:
    """A gap in the words a feed uses: 'just now', '42m ago', '4h ago', '9d ago'."""
    minutes = int(delta_seconds // 60)
    if minutes < 2:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    return f"{hours}h ago" if hours < 24 else f"{hours // 24}d ago"


def ago(moment: datetime | None) -> str | None:
    """How long ago something was published, or None when the source gave us no date.

    None is rendered as nothing at all, never as a guess like 'unknown' or today's date — an item
    with no timestamp must not be able to masquerade as fresh.
    """
    moment = aware(moment)
    if moment is None:
        return None
    return humanize((datetime.now(UTC) - moment).total_seconds())


def stamp(moment: datetime | None) -> str | None:
    """The absolute date, for the tooltip behind the relative one: '20 Aug 2026, 06:21 UTC'."""
    moment = aware(moment)
    if moment is None:
        return None
    return moment.strftime("%d %b %Y, %H:%M UTC")
