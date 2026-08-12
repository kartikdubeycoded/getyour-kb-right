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
    project_fit: str | None = None  # "<Project>: how it plugs into a build he's running now"
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
    # When the SOURCE published it — not when we fetched it. `created_at` only records when this row
    # was inserted, so on a re-fetch a three-day-old article looks as new as this morning's. This is
    # the field that makes "newest first" mean something. None when the source doesn't say (or says
    # something we don't trust — see app/freshness.py); those sort last.
    published_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    # breakdown — filled lazily on first view of the item's detail page (AI + README)
    overview: str | None = None  # plain 2-3 sentence what-it-is
    usage: str | None = None  # how you'd actually use it
    builds: str | None = None  # JSON list[str] — things you could build USING it
    product_ideas: str | None = None  # JSON list[str] — monetizable / product angles


class SavedItem(SQLModel, table=True):
    """A radar item the user chose to keep — a durable SNAPSHOT, not a flag on the live item.
    The corpus is wiped and re-inserted on every source refresh (store.replace_radar), so a saved
    flag there would vanish; copying the display fields here means the shortlist survives. Same
    display shape as RadarItem (source/title/url/summary/meta) so the card macro renders it as-is.
    `url` is the identity — saving the same item twice is a no-op."""

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    title: str
    url: str = Field(index=True, unique=True)  # identity: one save per item
    summary: str | None = None
    meta: str | None = None
    saved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SyncRun(SQLModel, table=True):
    """One pass of the radar refresh — the heartbeat's logbook.

    Two things need this to survive a restart. The header says "last synced 2h ago", which is a
    lie if it resets whenever the process does. And an item is NEW relative to the sync BEFORE the
    current one — items are wiped and re-inserted on every refresh (store.replace_radar), so their
    own created_at is always "just now" and can't answer "is this new to me?". Comparing an item's
    published_at against the previous run's start can."""

    id: int | None = Field(default=None, primary_key=True)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    finished_at: datetime | None = None  # None while in flight, or if the process died mid-sync
    results: str = ""  # JSON {source: bool} — which sources actually landed
    trigger: str = "schedule"  # "schedule" (the heartbeat) | "manual" (someone clicked SYNC)


class Idea(SQLModel, table=True):
    """A synthesized OPPORTUNITY — the app's real output. Not a link: a project to build or a paper
    to write, found by cross-referencing several radar items (news + repos + papers) and naming the
    gap between them. The user accepts or rejects each; accepted ideas are the shortlist we go deep
    on. This is where information becomes knowledge."""

    id: int | None = Field(default=None, primary_key=True)
    title: str                              # the idea's name
    kind: str = Field(default="build")      # "build" (a project/tool) | "paper" (a research paper)
    insight: str = ""                       # the pattern/gap across the sources, in plain words
    plan: str = ""                          # what to build (first step) OR a hypothesis to test
    why_you: str = ""                       # why it fits this person's focus, goals, reach
    sources: str = ""                       # JSON list[{title, source, url}] it came from
    status: str = Field(default="new", index=True)  # new | accepted | rejected
    depth: str | None = None                # the deep dive, generated on demand once accepted
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
