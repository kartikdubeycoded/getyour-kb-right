"""Data shapes. The Reel is the one row the whole pipeline fills in stage by stage."""

from datetime import UTC, datetime
from enum import StrEnum

from sqlmodel import Field, SQLModel


class ReelStatus(StrEnum):
    pending = "pending"  # ingested, not yet processed
    done = "done"  # transcribed + researched
    failed = "failed"  # something broke; see `error`


class Reel(SQLModel, table=True):
    """One shared reel and everything we learn about it.

    Fields fill in across the pipeline: ingest sets url+status=pending; transcription sets
    transcript; research sets summary/tools_links/tag/take and flips status to done (or failed).
    """

    id: int | None = Field(default=None, primary_key=True)
    url: str
    status: ReelStatus = Field(default=ReelStatus.pending)
    transcript: str | None = None
    summary: str | None = None
    tools_links: str | None = None  # JSON-encoded list[str] (v1 keeps it simple)
    tag: str | None = None  # course | tool | idea | other
    take: str | None = None  # the personalized do/skip take
    error: str | None = None  # failure reason when status == failed
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
