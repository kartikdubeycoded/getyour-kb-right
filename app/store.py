"""SQLite persistence for reels. Engine is configurable via DATABASE_URL (so Docker/tests can
point elsewhere). Functions read the module `engine` at call time (or take one explicitly), so
tests can swap in an in-memory DB."""

import json
import os
from datetime import UTC, datetime

from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Idea, RadarItem, Reel, SavedItem, SyncRun

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///reels.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


def init_db(eng=None) -> None:
    """Create tables if they don't exist, then add any columns missing from an older DB.
    (create_all makes NEW tables but never ALTERs an existing one — so new columns need this.)"""
    eng = eng or engine
    SQLModel.metadata.create_all(eng)
    _ensure_column(eng, "idea", "depth", "TEXT")
    _ensure_column(eng, "reel", "project_fit", "TEXT")
    _ensure_column(eng, "radaritem", "published_at", "DATETIME")


def _ensure_column(eng, table: str, column: str, decl: str) -> None:
    """Add `column` to `table` if it isn't there yet — a minimal forward migration for SQLite."""
    with eng.connect() as conn:
        existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            conn.commit()


def save_reel(reel: Reel, eng=None) -> Reel:
    """Insert (id is None) or update (id set) a reel. Returns it with id/defaults populated."""
    with Session(eng or engine) as session:
        merged = session.merge(reel)  # merge handles both insert and update of detached objects
        session.commit()
        session.refresh(merged)
        return merged


def get_reel(reel_id: int, eng=None) -> Reel | None:
    with Session(eng or engine) as session:
        return session.get(Reel, reel_id)


def list_recent(limit: int = 50, eng=None) -> list[Reel]:
    """Most-recently-created reels first."""
    with Session(eng or engine) as session:
        stmt = select(Reel).order_by(Reel.created_at.desc(), Reel.id.desc()).limit(limit)
        return list(session.exec(stmt))


def replace_radar(source: str, items: list[RadarItem], eng=None) -> None:
    """Swap in a fresh batch for one radar source: drop the old, insert the new (one txn)."""
    with Session(eng or engine) as session:
        for old in session.exec(select(RadarItem).where(RadarItem.source == source)):
            session.delete(old)
        for item in items:
            session.add(item)
        session.commit()


def get_radar_item(item_id: int, eng=None) -> RadarItem | None:
    with Session(eng or engine) as session:
        return session.get(RadarItem, item_id)


def save_radar_item(item: RadarItem, eng=None) -> RadarItem:
    """Insert or update a single radar item (used to cache its lazy AI breakdown)."""
    with Session(eng or engine) as session:
        merged = session.merge(item)
        session.commit()
        session.refresh(merged)
        return merged


def find_or_create_github_item(full_name: str, url: str, eng=None) -> RadarItem:
    """Return the existing github radar item for this repo, or create a bare one. Lets a reel link
    to a repo's breakdown even when the radar hasn't pulled it — the breakdown fills in on view."""
    with Session(eng or engine) as session:
        existing = session.exec(
            select(RadarItem).where(RadarItem.source == "github", RadarItem.url == url)
        ).first()
        if existing is not None:
            return existing
        item = RadarItem(source="github", title=full_name, url=url, meta="via reel")
        session.add(item)
        session.commit()
        session.refresh(item)
        return item


def list_all_radar(limit: int = 300, eng=None) -> list[RadarItem]:
    """Every radar item across all sources, genuinely newest first — the corpus the lanes, the home
    page and the Idea Space all curate from. Ordered by when the SOURCE published each item, not by
    when we happened to insert it: on a re-fetch the insert order just mirrors the fetch loop, so
    a three-day-old article would outrank this morning's purely by arriving later."""
    with Session(eng or engine) as session:
        return list(session.exec(_freshest_first(select(RadarItem)).limit(limit)))


def save_radar(radar_id: int, eng=None) -> SavedItem | None:
    """Snapshot a live radar item into the durable shortlist. Idempotent by url (saving the same
    item twice returns the existing row). Returns None if the radar item doesn't exist."""
    with Session(eng or engine) as session:
        item = session.get(RadarItem, radar_id)
        if item is None:
            return None
        existing = session.exec(select(SavedItem).where(SavedItem.url == item.url)).first()
        if existing is not None:
            return existing
        saved = SavedItem(
            source=item.source, title=item.title, url=item.url,
            summary=item.summary, meta=item.meta,
        )
        session.add(saved)
        session.commit()
        session.refresh(saved)
        return saved


def unsave(url: str, eng=None) -> None:
    """Drop an item from the shortlist (by url)."""
    with Session(eng or engine) as session:
        for row in session.exec(select(SavedItem).where(SavedItem.url == url)):
            session.delete(row)
        session.commit()


def list_saved(eng=None) -> list[SavedItem]:
    """The shortlist, most-recently-saved first."""
    with Session(eng or engine) as session:
        stmt = select(SavedItem).order_by(SavedItem.saved_at.desc(), SavedItem.id.desc())
        return list(session.exec(stmt))


def saved_urls(eng=None) -> set[str]:
    """The set of saved urls — so feed cards can show whether an item is already kept."""
    with Session(eng or engine) as session:
        return set(session.exec(select(SavedItem.url)))


# ---- the heartbeat's logbook ----


def start_sync(trigger: str = "schedule", eng=None) -> int:
    """Open a sync record and return its id. Written BEFORE the fetches so a run that dies halfway
    still leaves a trace (finished_at stays None) instead of vanishing."""
    with Session(eng or engine) as session:
        run = SyncRun(trigger=trigger)
        session.add(run)
        session.commit()
        session.refresh(run)
        return run.id


def finish_sync(run_id: int, results: dict[str, bool], eng=None) -> None:
    """Close a sync record with the per-source outcome."""
    with Session(eng or engine) as session:
        run = session.get(SyncRun, run_id)
        if run is None:
            return
        run.finished_at = datetime.now(UTC)
        run.results = json.dumps(results)
        session.add(run)
        session.commit()


def recent_syncs(limit: int = 2, eng=None) -> list[SyncRun]:
    """The most recent completed syncs, newest first. Two is what the UI needs: the latest for
    "last synced Nh ago", and the one before it as the cutoff for what counts as NEW."""
    with Session(eng or engine) as session:
        stmt = (
            select(SyncRun)
            .where(SyncRun.finished_at.is_not(None))
            .order_by(SyncRun.started_at.desc(), SyncRun.id.desc())
            .limit(limit)
        )
        return list(session.exec(stmt))


def new_since(eng=None) -> datetime | None:
    """The cutoff an item must beat to count as NEW: the start of the PREVIOUS completed sync.

    Not the latest sync — every item is re-inserted by the run that just finished, so measuring
    against it would mark either everything or nothing. Measuring against the one before it answers
    the question the badge actually asks: "did this show up since I last looked?" None until two
    syncs exist, which correctly means "nothing is new yet"."""
    runs = recent_syncs(2, eng)
    return runs[1].started_at if len(runs) > 1 else None


# Sources where RECENCY is the point and `score` carries little ordering information: news/gnews
# score is a topic-match count that ties constantly, and arXiv sets score=0 outright. Everywhere
# else the score is a deliberate ranking we must not override — GitHub's is star count, trending's
# encodes rank, and opps' encodes relevance-then-urgency (a hackathon three weeks out in your field
# beats a generic one closing Friday). Sorting those by date would silently undo that work.
_TIME_SORTED = {"news", "gnews", "arxiv"}


def _freshest_first(stmt):
    """Newest published first, unknown dates last. `published_at IS NULL` sorts False(0) before
    True(1), which is how SQLite spells NULLS LAST; the id tiebreak keeps ordering stable for items
    sharing a timestamp (or all missing one)."""
    return stmt.order_by(
        RadarItem.published_at.is_(None),
        RadarItem.published_at.desc(),
        RadarItem.id.desc(),
    )


def list_radar(source: str, limit: int = 50, eng=None) -> list[RadarItem]:
    """Items for one radar source. Time-driven sources come back freshest first; the rest keep
    their source's own ranking (see _TIME_SORTED)."""
    with Session(eng or engine) as session:
        stmt = select(RadarItem).where(RadarItem.source == source)
        stmt = (
            _freshest_first(stmt)
            if source in _TIME_SORTED
            else stmt.order_by(RadarItem.score.desc(), RadarItem.id.desc())
        )
        return list(session.exec(stmt.limit(limit)))


# ---- Idea Space ----

def add_ideas(ideas: list[dict], eng=None) -> list[Idea]:
    """Persist a batch of freshly synthesized ideas (status 'new'). Each dict is the shape returned
    by synthesize.synthesize_ideas; `sources` is stored as JSON. Returns the saved rows."""
    saved: list[Idea] = []
    with Session(eng or engine) as session:
        for d in ideas:
            row = Idea(
                title=d.get("title", ""),
                kind=d.get("kind", "build"),
                insight=d.get("insight", ""),
                plan=d.get("plan", ""),
                why_you=d.get("why_you", ""),
                sources=json.dumps(d.get("sources") or []),
            )
            session.add(row)
            saved.append(row)
        session.commit()
        for row in saved:
            session.refresh(row)
    return saved


def list_ideas(status: str | None = None, limit: int = 60, eng=None) -> list[Idea]:
    """Ideas newest first, optionally filtered by status (new | accepted | rejected)."""
    with Session(eng or engine) as session:
        stmt = select(Idea)
        if status:
            stmt = stmt.where(Idea.status == status)
        stmt = stmt.order_by(Idea.created_at.desc(), Idea.id.desc()).limit(limit)
        return list(session.exec(stmt))


def set_idea_status(idea_id: int, status: str, eng=None) -> Idea | None:
    """Accept or reject an idea. Returns the updated row, or None if it doesn't exist."""
    with Session(eng or engine) as session:
        idea = session.get(Idea, idea_id)
        if idea is None:
            return None
        idea.status = status
        session.add(idea)
        session.commit()
        session.refresh(idea)
        return idea


def get_idea(idea_id: int, eng=None) -> Idea | None:
    with Session(eng or engine) as session:
        return session.get(Idea, idea_id)


def set_idea_depth(idea_id: int, depth: str, eng=None) -> Idea | None:
    """Cache an idea's generated deep dive. Returns the updated row, or None if it doesn't exist."""
    with Session(eng or engine) as session:
        idea = session.get(Idea, idea_id)
        if idea is None:
            return None
        idea.depth = depth
        session.add(idea)
        session.commit()
        session.refresh(idea)
        return idea
