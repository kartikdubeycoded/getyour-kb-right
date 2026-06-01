"""SQLite persistence for reels. Engine is configurable via DATABASE_URL (so Docker/tests can
point elsewhere). Functions read the module `engine` at call time (or take one explicitly), so
tests can swap in an in-memory DB."""

import os

from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Reel

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
