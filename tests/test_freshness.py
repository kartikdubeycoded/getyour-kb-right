"""Publish-time parsing and freshness ordering.

The corpus used to sort by insert order, which meant "newest" only ever described the order our
fetch loop happened to run in. These tests pin the two halves of the fix: every source's own time
format parses into a comparable UTC datetime, and the corpus really does come back newest-first.
"""

import calendar
import time
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, SQLModel, create_engine

from app import freshness, store
from app.models import RadarItem


def _engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return eng


def _add(eng, **kwargs):
    with Session(eng) as session:
        session.add(RadarItem(**kwargs))
        session.commit()


# --- parsing each source's shape ---


def test_struct_time_is_read_as_utc_not_local_time():
    """feedparser normalizes every feed to UTC. time.mktime would read that struct as LOCAL time
    and shift it by the machine's offset (5.5h in IST) — enough to mis-order the feed against the
    epoch-based sources. Pin that we use the UTC reading."""
    moment = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    struct = time.gmtime(calendar.timegm(moment.timetuple()))
    assert freshness.from_struct_time(struct) == moment


def test_epoch_seconds_parse():
    """Algolia's created_at_i (HN) and Reddit's created_utc."""
    moment = datetime(2026, 7, 30, 8, 30, tzinfo=UTC)
    assert freshness.from_epoch(moment.timestamp()) == moment


def test_iso_with_trailing_z_parses():
    """GitHub's pushed_at ends in 'Z', which datetime.fromisoformat rejects on some shapes."""
    assert freshness.from_iso("2026-07-30T12:00:00Z") == datetime(2026, 7, 30, 12, 0, tzinfo=UTC)


def test_naive_iso_is_assumed_utc():
    """A date with no offset must still come back aware — comparing naive to aware raises when
    the corpus is sorted."""
    parsed = freshness.from_iso("2026-07-30T12:00:00")
    assert parsed is not None and parsed.tzinfo is not None


def test_unparseable_values_return_none_rather_than_a_guess():
    """A wrong timestamp is worse than none: it would pin a stale item to the top of the feed."""
    assert freshness.from_iso("not a date") is None
    assert freshness.from_iso("") is None
    assert freshness.from_epoch(None) is None
    assert freshness.from_epoch("") is None
    assert freshness.from_struct_time(None) is None


def test_a_date_from_the_future_is_rejected():
    """Publishers do get this wrong. Left alone, one bad feed would own the top of the page
    forever, so anything implausibly far ahead degrades to None."""
    ahead = datetime.now(UTC) + timedelta(days=30)
    assert freshness.from_iso(ahead.isoformat()) is None


def test_a_slightly_future_date_is_kept():
    """Timezone slop of a few hours is normal and must NOT be thrown away."""
    soon = datetime.now(UTC) + timedelta(hours=6)
    assert freshness.from_iso(soon.isoformat()) is not None


# --- ordering ---


def test_an_older_item_never_outranks_a_newer_one_regardless_of_insert_order():
    """The whole point of T1. The stale item is inserted LAST, so under the old id-desc ordering it
    would have sat on top of the page."""
    eng = _engine()
    now = datetime.now(UTC)
    _add(eng, source="news", title="an hour ago", url="u1", published_at=now - timedelta(hours=1))
    _add(eng, source="news", title="three days ago", url="u2", published_at=now - timedelta(days=3))

    titles = [item.title for item in store.list_all_radar(eng=eng)]
    assert titles == ["an hour ago", "three days ago"]


def test_items_with_no_publish_date_sort_last_but_are_not_dropped():
    """Sources that don't report a time (opps) must still appear — just below the dated ones."""
    eng = _engine()
    old = datetime.now(UTC) - timedelta(days=10)
    _add(eng, source="opps", title="undated", url="u1")
    _add(eng, source="news", title="dated but old", url="u2", published_at=old)

    titles = [item.title for item in store.list_all_radar(eng=eng)]
    assert titles == ["dated but old", "undated"]


def test_news_tab_is_freshest_first():
    """news scores are topic-match counts that tie constantly, so recency is what orders the tab."""
    eng = _engine()
    now = datetime.now(UTC)
    _add(eng, source="news", title="older", url="u1", score=5, published_at=now - timedelta(days=2))
    _add(eng, source="news", title="newer", url="u2", score=5, published_at=now)

    assert [i.title for i in store.list_radar("news", eng=eng)] == ["newer", "older"]


def test_github_tab_keeps_star_ranking_and_is_not_reordered_by_date():
    """A repo pushed today with 12 stars must NOT displace a 40k-star project. github/trending/opps
    scores are deliberate rankings; only _TIME_SORTED sources reorder by date."""
    eng = _engine()
    now = datetime.now(UTC)
    _add(eng, source="github", title="huge", url="u1", score=40000,
         published_at=now - timedelta(days=5))
    _add(eng, source="github", title="tiny but fresh", url="u2", score=12, published_at=now)

    assert [i.title for i in store.list_radar("github", eng=eng)] == ["huge", "tiny but fresh"]


def test_opps_keeps_its_relevance_then_urgency_ranking():
    """opps score encodes relevance-then-urgency; sorting it by date would undo that work."""
    eng = _engine()
    now = datetime.now(UTC)
    _add(eng, source="opps", title="relevant", url="u1", score=85, published_at=now - timedelta(1))
    _add(eng, source="opps", title="generic", url="u2", score=30, published_at=now)

    assert [i.title for i in store.list_radar("opps", eng=eng)] == ["relevant", "generic"]
