"""SQLite persistence for reels. Engine is configurable via DATABASE_URL (so Docker/tests can
point elsewhere). Functions read the module `engine` at call time (or take one explicitly), so
tests can swap in an in-memory DB."""

import os

from sqlmodel import Session, SQLModel, create_engine, select

from app.models import RadarItem, Reel

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
