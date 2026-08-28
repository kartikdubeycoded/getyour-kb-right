"""The 6-hourly heartbeat: the radar refreshing itself.

These cover the parts that decide whether the thing is trustworthy rather than just present — that
a failing sync can't kill the schedule, that the run is recorded even when it dies, and that "NEW"
means something defensible.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy.pool import StaticPool
from sqlmodel import create_engine

from app import heartbeat, main, store
from app.models import RadarItem


def _memory_engine():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    store.init_db(eng)
    return eng


# --- interval configuration ---


def test_interval_defaults_to_six_hours(monkeypatch):
    monkeypatch.delenv("REFRESH_HOURS", raising=False)
    assert heartbeat.interval_hours() == 6.0


def test_interval_is_env_overridable(monkeypatch):
    """So a live check can watch two cycles fire without waiting a quarter of a day."""
    monkeypatch.setenv("REFRESH_HOURS", "0.02")
    assert heartbeat.interval_hours() == 0.02


def test_a_nonsense_interval_falls_back_instead_of_crashing(monkeypatch):
    """A typo'd env var must not stop the heartbeat starting — a silently dead scheduler is the
    worst outcome, because the site would just quietly stop updating."""
    monkeypatch.setenv("REFRESH_HOURS", "every 6 hours")
    assert heartbeat.interval_hours() == 6.0


def test_a_zero_or_negative_interval_falls_back(monkeypatch):
    """APScheduler rejects a non-positive interval; falling back keeps the job alive."""
    monkeypatch.setenv("REFRESH_HOURS", "0")
    assert heartbeat.interval_hours() == 6.0


# --- the beat itself ---


def test_a_beat_records_the_run_and_its_results(monkeypatch):
    eng = _memory_engine()
    monkeypatch.setattr(store, "engine", eng)
    monkeypatch.setattr(main, "refresh_everything", lambda: {"news": True, "github": False})

    results = heartbeat.run_refresh()

    assert results == {"news": True, "github": False}
    runs = store.recent_syncs(eng=eng)
    assert len(runs) == 1
    assert runs[0].finished_at is not None
    assert runs[0].trigger == "schedule"


def test_a_failing_refresh_does_not_propagate(monkeypatch):
    """A raising job gets dropped by the scheduler — one bad night would stop the radar forever.
    The run must still be closed out so it doesn't look like it's permanently in flight."""
    eng = _memory_engine()
    monkeypatch.setattr(store, "engine", eng)

    def boom():
        raise RuntimeError("every source is down")

    monkeypatch.setattr(main, "refresh_everything", boom)

    assert heartbeat.run_refresh() == {}  # swallowed, not raised
    runs = store.recent_syncs(eng=eng)
    assert len(runs) == 1 and runs[0].finished_at is not None


def test_the_job_is_registered_with_overlap_protection(monkeypatch):
    """max_instances=1 stops a slow sync being overlapped by the next one — two concurrent runs
    race each other through replace_radar and can leave a source half-written. coalesce collapses
    the backlog after the laptop sleeps through several firings."""
    import asyncio

    async def scenario():
        monkeypatch.setenv("REFRESH_HOURS", "6")
        scheduler = heartbeat.start()
        try:
            job = scheduler.get_job(heartbeat.JOB_ID)
            assert job is not None
            assert job.max_instances == 1
            assert job.coalesce is True
        finally:
            scheduler.shutdown(wait=False)

    asyncio.run(scenario())  # AsyncIOScheduler.start() needs a running event loop


# --- what counts as NEW ---


def test_nothing_is_new_until_two_syncs_exist():
    """With one sync there's no 'before' to compare against, so nothing should be badged."""
    eng = _memory_engine()
    store.finish_sync(store.start_sync(eng=eng), {"news": True}, eng)

    assert store.new_since(eng) is None


def test_new_cutoff_is_the_previous_sync_not_the_latest():
    """Items are wiped and re-inserted on every refresh, so measuring against the run that just
    finished would mark either everything or nothing. The run BEFORE it is the honest cutoff."""
    eng = _memory_engine()
    first = store.start_sync(eng=eng)
    store.finish_sync(first, {"news": True}, eng)
    second = store.start_sync(eng=eng)
    store.finish_sync(second, {"news": True}, eng)

    cutoff = store.new_since(eng)

    runs = store.recent_syncs(2, eng)
    assert cutoff == runs[1].started_at  # the older of the two


def test_an_unfinished_run_is_not_counted_as_a_sync():
    """A process killed mid-sync leaves finished_at unset. That run is evidence of a failure, not
    a completed sync, so it must not move the 'last synced' clock."""
    eng = _memory_engine()
    store.finish_sync(store.start_sync(eng=eng), {"news": True}, eng)
    store.start_sync(eng=eng)  # in flight, never finished

    assert len(store.recent_syncs(5, eng)) == 1


def test_is_new_marks_only_items_published_since_the_previous_sync(monkeypatch):
    eng = _memory_engine()
    monkeypatch.setattr(store, "engine", eng)
    store.finish_sync(store.start_sync(eng=eng), {}, eng)
    cutoff_run_time = datetime.now(UTC)
    store.finish_sync(store.start_sync(eng=eng), {}, eng)
    main._cutoff_cache = (0.0, None)  # bypass the per-render cache

    fresh = RadarItem(source="news", title="t", url="u", published_at=cutoff_run_time)
    stale = RadarItem(
        source="news", title="t", url="u", published_at=cutoff_run_time - timedelta(days=2)
    )
    undated = RadarItem(source="opps", title="t", url="u")

    assert main.is_new(fresh) is True
    assert main.is_new(stale) is False
    assert main.is_new(undated) is False  # no date means we can't claim it's new


# --- what the header says ---


def test_header_says_not_synced_when_nothing_has_run(monkeypatch):
    eng = _memory_engine()
    monkeypatch.setattr(store, "engine", eng)

    assert main.sync_status()["ever"] is False


def test_header_reports_how_long_ago_and_what_is_next(monkeypatch):
    eng = _memory_engine()
    monkeypatch.setattr(store, "engine", eng)
    monkeypatch.setenv("REFRESH_HOURS", "6")
    monkeypatch.delenv("DISABLE_HEARTBEAT", raising=False)
    store.finish_sync(store.start_sync(eng=eng), {"news": True}, eng)

    status = main.sync_status()

    assert status["ever"] is True
    assert status["ago"] == "just now"
    assert status["scheduled"] is True


def test_header_promises_no_next_sync_when_the_scheduler_is_off(monkeypatch):
    """Promising a refresh that will never arrive is worse than saying nothing."""
    eng = _memory_engine()
    monkeypatch.setattr(store, "engine", eng)
    monkeypatch.setenv("DISABLE_HEARTBEAT", "1")
    store.finish_sync(store.start_sync(eng=eng), {"news": True}, eng)

    assert main.sync_status()["scheduled"] is False


# --- the Telegram digest ---


def test_digest_measures_new_on_published_at_not_created_at(monkeypatch):
    """The trap this guards: every sync calls replace_radar, which deletes and re-inserts the whole
    corpus, so created_at is fresh for EVERY row on every beat. Filtering on it would announce all
    ~360 items as new every six hours — which is exactly how a notification channel gets muted.
    published_at is when the SOURCE published, so it answers the question the digest really asks."""
    eng = _memory_engine()
    # two completed syncs so new_since() has a cutoff (the start of the PREVIOUS run)
    old = store.start_sync(eng=eng)
    store.finish_sync(old, {"news": True}, eng=eng)
    recent = store.start_sync(eng=eng)
    store.finish_sync(recent, {"news": True}, eng=eng)
    cutoff = store.new_since(eng)
    assert cutoff is not None

    store.replace_radar(
        "news",
        [
            RadarItem(
                source="news",
                title="stale article",
                url="https://e.com/old",
                published_at=cutoff - timedelta(days=3),
            ),
            RadarItem(
                source="news",
                title="genuinely new article",
                url="https://e.com/new",
                published_at=cutoff + timedelta(minutes=5),
            ),
        ],
        eng=eng,
    )

    sent = {}

    def capture(text):
        sent["text"] = text
        return True

    monkeypatch.setattr(heartbeat.notify, "send_telegram", capture)

    assert heartbeat._push_digest(eng) is True
    assert "genuinely new article" in sent["text"]
    assert "stale article" not in sent["text"]


def test_digest_sends_nothing_when_nothing_is_new(monkeypatch):
    """A "nothing new" ping every six hours is how a notifier earns a mute."""
    eng = _memory_engine()
    calls = []
    monkeypatch.setattr(heartbeat.notify, "send_telegram", lambda text: calls.append(text) or True)

    assert heartbeat._push_digest(eng) is False
    assert calls == []


def test_a_broken_digest_cannot_sink_the_beat(monkeypatch):
    """Same rule as send_telegram never raising: the notifier is a convenience and must never be
    able to take the radar down with it."""
    eng = _memory_engine()

    def boom(*_a, **_k):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(heartbeat.store, "new_since", boom)

    assert heartbeat._push_digest(eng) is False  # returns, does not raise


# --- when the FIRST beat lands (the staleness bug) ---
#
# The radar sat nine days stale with a "healthy" scheduler running: an interval job with no start
# time fires one full interval after startup, so a 6-hourly beat on a laptop that is never up for
# six unbroken hours never beat at all. These pin the fix — the clock decides, not the uptime.


def test_first_beat_is_immediate_when_nothing_has_ever_synced(monkeypatch):
    monkeypatch.setattr(store, "recent_syncs", lambda limit=1, eng=None: [])
    now = datetime.now(UTC)
    first = heartbeat.first_beat_at(6.0, now=now)
    assert first == now + timedelta(seconds=heartbeat.STARTUP_GRACE_SECONDS)


def test_first_beat_is_immediate_when_the_last_sync_is_overdue(monkeypatch):
    """The real reported case: last sync nine days ago, app restarted, corpus must refresh now."""
    stale = datetime.now(UTC) - timedelta(days=9)
    monkeypatch.setattr(
        store, "recent_syncs", lambda limit=1, eng=None: [_finished(stale)]
    )
    now = datetime.now(UTC)
    assert heartbeat.first_beat_at(6.0, now=now) == now + timedelta(
        seconds=heartbeat.STARTUP_GRACE_SECONDS
    )


def test_a_recent_sync_is_not_refetched_on_every_restart(monkeypatch):
    """The other half: restarting three times in a minute must not trigger three full syncs. The
    next beat is one interval after the last SYNC, not one interval after this process booted."""
    recent = datetime.now(UTC) - timedelta(hours=1)
    monkeypatch.setattr(
        store, "recent_syncs", lambda limit=1, eng=None: [_finished(recent)]
    )
    assert heartbeat.first_beat_at(6.0) == recent + timedelta(hours=6)


def test_a_naive_stored_timestamp_is_treated_as_utc(monkeypatch):
    """SQLite returns naive datetimes; comparing one to an aware `now` raises. A crash here would
    take the scheduler down at startup, which is exactly when it must not fail."""
    naive_recent = (datetime.now(UTC) - timedelta(hours=1)).replace(tzinfo=None)
    monkeypatch.setattr(
        store, "recent_syncs", lambda limit=1, eng=None: [_finished(naive_recent)]
    )
    first = heartbeat.first_beat_at(6.0)
    assert first.tzinfo is not None


def test_an_unreadable_logbook_still_beats(monkeypatch):
    """A broken sync table must leave the radar refreshing, not silently frozen forever."""

    def boom(limit=1, eng=None):
        raise RuntimeError("no such table: syncrun")

    monkeypatch.setattr(store, "recent_syncs", boom)
    now = datetime.now(UTC)
    assert heartbeat.first_beat_at(6.0, now=now) == now + timedelta(
        seconds=heartbeat.STARTUP_GRACE_SECONDS
    )


class _finished:
    """Minimal stand-in for a SyncRun row: the only field first_beat_at reads."""

    def __init__(self, finished_at):
        self.finished_at = finished_at
