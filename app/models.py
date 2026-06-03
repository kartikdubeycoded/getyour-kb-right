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
    transcript: str | None = None  # what we HEAR (whisper on the audio)
    caption: str | None = None  # what we READ (the creator's caption, via yt-dlp)
    visual: str | None = None  # what we SEE (on-screen text + scene, via the vision model)
    thumbnail_url: str | None = None  # cover frame URL, shown on the card/detail
    summary: str | None = None
    tools_links: str | None = None  # JSON-encoded list[str] (v1 keeps it simple)
    key_takeaways: str | None = None  # JSON-encoded list[str] — the bullet points worth keeping
    tag: str | None = None  # course | tool | idea | other
    take: str | None = None  # the personalized do/skip take
    buildable: str | None = None  # "yes" | "no" — can something useful be built from this?
    build_idea: str | None = None  # if buildable: what to build
    monetization: str | None = None  # if buildable: worst-case how to earn from it
    error: str | None = None  # failure reason when status == failed
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RadarItem(SQLModel, table=True):
    """One item from a tech-radar source (GitHub now; Reddit / HN / arXiv later). The radar is the
    'other apps' next to reels — continuous signal on where tech is moving, ranked for the user."""

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)  # "github" | "reddit" | "hn" | ...
    title: str
    url: str
    summary: str | None = None  # the item's own description
    meta: str | None = None  # display chip, e.g. "⭐ 12.3k · Python"
    score: int = 0  # for ranking within a source (stars, upvotes, points)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    # breakdown — filled lazily on first view of the item's detail page (AI + README)
    overview: str | None = None  # plain 2-3 sentence what-it-is
    usage: str | None = None  # how you'd actually use it
    builds: str | None = None  # JSON list[str] — things you could build USING it
    product_ideas: str | None = None  # JSON list[str] — monetizable / product angles
