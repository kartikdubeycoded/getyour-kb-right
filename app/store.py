"""SQLite persistence for reels. Engine is configurable via DATABASE_URL (so Docker/tests can
point elsewhere). Functions read the module `engine` at call time (or take one explicitly), so
tests can swap in an in-memory DB."""

import os

from sqlmodel import Session, SQLModel, create_engine, select

from app.models import RadarItem, Reel, SavedItem

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///reels.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


def init_db(eng=None) -> None:
    """Create tables if they don't exist."""
    SQLModel.metadata.create_all(eng or engine)


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
    """Every radar item across all sources, newest first — the corpus the lanes curate from."""
    with Session(eng or engine) as session:
        stmt = select(RadarItem).order_by(RadarItem.id.desc()).limit(limit)
        return list(session.exec(stmt))


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


def list_radar(source: str, limit: int = 50, eng=None) -> list[RadarItem]:
    """Items for one radar source, highest score first."""
    with Session(eng or engine) as session:
        stmt = (
            select(RadarItem)
            .where(RadarItem.source == source)
            .order_by(RadarItem.score.desc(), RadarItem.id.desc())
            .limit(limit)
        )
        return list(session.exec(stmt))
