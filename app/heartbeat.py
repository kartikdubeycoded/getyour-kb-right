"""The 6-hourly heartbeat: the radar refreshing itself, with nobody clicking anything.

Until now the corpus only moved when someone hit SYNC, which meant the site was as stale as the
last time you remembered to open it. This runs `main.refresh_everything` on a timer inside the app
process — no external cron, no second service to keep alive.

**What this does NOT do:** it cannot refresh while the machine is off. Free always-on hosting needs
a card, which is out of scope (see DEPLOY.md), so the honest promise is "fresh while the app runs",
and the header states the last sync time rather than implying continuous coverage.

Two safety rules, both deliberate:

* `max_instances=1` — a sync can outlive its slot (a slow arXiv, a rate-limited GitHub). Without
  this, APScheduler would start a second overlapping run that races the first through
  `replace_radar` and can leave a source half-written.
* `coalesce=True` — if the machine sleeps through three firings, run ONCE on wake, not three times
  back to back. The three runs would fetch identical data and just burn rate limit.
"""

import asyncio
import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app import notify, store

# Hours between automatic refreshes. Env-overridable mainly so a test (or a live check) can set
# something tiny and watch two cycles fire without waiting a quarter of a day.
DEFAULT_HOURS = 6.0
JOB_ID = "radar-refresh"


def interval_hours() -> float:
    """The configured gap, falling back to 6h if REFRESH_HOURS is missing or nonsense. A bad value
    must not stop the heartbeat starting — a silently dead scheduler is the worst outcome here."""
    try:
        hours = float(os.getenv("REFRESH_HOURS", DEFAULT_HOURS))
    except (TypeError, ValueError):
        return DEFAULT_HOURS
    return hours if hours > 0 else DEFAULT_HOURS


def _push_digest(eng=None) -> bool:
    """Tell Katti what landed, over Telegram. Returns whether a message actually went out.

    "New" is measured on `published_at`, NOT `created_at`. Every sync calls `replace_radar`, which
    deletes and re-inserts every row, so `created_at` is fresh for the entire corpus on every beat —
    filtering on it would announce all ~360 items as new, every six hours, which is precisely how a
    notification channel gets muted. `published_at` is when the SOURCE published, so it answers the
    question the digest actually asks: what appeared since I last looked?

    Wrapped whole in a try/except for the same reason `send_telegram` never raises: a notifier is a
    convenience, and it must not be able to take the radar down with it.
    """
    try:
        cutoff = store.new_since(eng)
        corpus = store.list_all_radar(limit=300, eng=eng)
        fresh = (
            [i for i in corpus if i.published_at and cutoff and i.published_at > cutoff]
            if cutoff
            else []
        )
        text = notify.build_digest(
            ideas=store.list_ideas(status="pending", limit=3, eng=eng),
            opps=store.list_radar("opps", limit=3, eng=eng),
            items=fresh,
        )
        if not text:
            logging.info("heartbeat: nothing new worth pushing")
            return False
        return notify.send_telegram(text)
    except Exception:  # noqa: BLE001 — a broken digest must never sink the beat
        logging.exception("heartbeat: digest failed")
        return False


def run_refresh() -> dict[str, bool]:
    """One beat: refresh every source, recording the run either way.

    The record is opened before the fetches and closed after, so a crash mid-sync leaves a row with
    finished_at unset — visible evidence of a failed run rather than silence. Exceptions are logged
    and swallowed: a raising job would be dropped by the scheduler, and one bad night would stop
    the radar forever.
    """
    from app import main  # deferred: main imports this module, so importing it up top would cycle

    run_id = store.start_sync(trigger="schedule")
    try:
        results = main.refresh_everything()
    except Exception:  # noqa: BLE001 — the heartbeat must survive anything a source throws
        logging.exception("heartbeat: refresh failed")
        store.finish_sync(run_id, {})
        return {}
    landed = [s for s, ok in results.items() if ok]
    failed = [s for s, ok in results.items() if not ok]
    logging.info("heartbeat: refreshed %s%s", ", ".join(landed) or "nothing",
                 f" (failed: {', '.join(failed)})" if failed else "")
    store.finish_sync(run_id, results)
    # After finish_sync, never before: the digest's "what's new" cutoff is derived from the sync
    # history, so this run has to be on the record before we ask what changed.
    _push_digest()
    return results


async def _beat() -> None:
    """Run the sync off the event loop. refresh_everything is blocking network + SQLite work; on
    the loop thread it would freeze every request served for the length of a full sync."""
    await asyncio.to_thread(run_refresh)


def start(scheduler: AsyncIOScheduler | None = None) -> AsyncIOScheduler:
    """Begin beating. Returns the scheduler so the caller can shut it down on app exit."""
    scheduler = scheduler or AsyncIOScheduler()
    hours = interval_hours()
    scheduler.add_job(
        _beat,
        "interval",
        hours=hours,
        id=JOB_ID,
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )
    scheduler.start()
    logging.info("heartbeat: refreshing every %sh", hours)
    return scheduler
