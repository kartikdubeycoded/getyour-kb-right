"""FastAPI app: ingest webhook + dashboard. The pipeline behind /ingest is stubbed in v1's
walking skeleton; real stages swap in across Tasks 4-6."""

import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

load_dotenv()  # read .env in dev (NVIDIA_API_KEY etc.) — must run before importing
# app.research, which reads NIM_MODEL/NIM_DRAFT_MODEL into module-level constants at
# import time; importing it first would silently freeze those to their hardcoded defaults.

from app import (
    arxiv_radar,
    auth,
    cards,
    freshness,
    github_radar,
    gnews_radar,
    heartbeat,
    hn_radar,
    lanes,
    last30days_bridge,
    opportunity_radar,
    reddit_radar,
    research,
    rss_radar,
    store,
    synthesize,
    yc_rfs,
)
from app.ingest import process_reel
from app.models import Reel
from app.profile import load_profile
from app.repo_link import find_repo
from app.thumbs import THUMB_DIR

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init_db()
    scheduler = heartbeat.start() if os.getenv("DISABLE_HEARTBEAT") != "1" else None
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)


app = FastAPI(title="get-your-knowledge-right", lifespan=lifespan)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# The clock lives in app/freshness.py — one implementation, so the header's "synced 4h ago" and a
# card's "4h ago" can never drift apart. These names stay as the local vocabulary of this module.
_aware = freshness.aware
_ago = freshness.humanize


def sync_status() -> dict:
    """What the header reports about the heartbeat. `next_in` is deliberately omitted when the
    scheduler is off — promising a next sync that will never come is worse than saying nothing."""
    runs = store.recent_syncs(1)
    last = _aware(runs[0].finished_at) if runs else None
    if last is None:
        return {"ever": False, "every": heartbeat.interval_hours()}
    elapsed = (datetime.now(UTC) - last).total_seconds()
    every = heartbeat.interval_hours()
    remaining = max(0.0, every * 3600 - elapsed)
    return {
        "ever": True,
        "ago": _ago(elapsed),
        "every": every,
        "next_in": f"{int(remaining // 3600)}h" if remaining >= 3600 else "under an hour",
        "scheduled": os.getenv("DISABLE_HEARTBEAT") != "1",
    }


# The NEW cutoff is the same for every card on a page, but the macro asks per item — so cache it
# briefly rather than issuing one query per card.
_CUTOFF_TTL = 5.0
_cutoff_cache: tuple[float, object] = (0.0, None)


def is_new(item) -> bool:
    """Did this item publish since the sync before last? See store.new_since for why it's measured
    against the PREVIOUS run and not the latest one."""
    global _cutoff_cache
    now = time.monotonic()
    if now - _cutoff_cache[0] > _CUTOFF_TTL:
        _cutoff_cache = (now, store.new_since())
    cutoff = _cutoff_cache[1]
    published = _aware(getattr(item, "published_at", None))
    return bool(cutoff and published and published >= _aware(cutoff))


def safe_url(value: str | None) -> str:
    """Render a stored URL as a link target only if it is actually a web address.

    Item URLs are NOT ours: they arrive from RSS `<link>` elements, search APIs and LLM-extracted
    text. A hostile or malformed feed can therefore put `javascript:...` into `item.url`, and
    autoescaping does NOT help — it escapes the quotes so the attribute can't be broken out of, but
    a `javascript:` value inside a well-formed href still executes on click.

    Allowing only http/https (and site-relative paths) closes the whole scheme class — javascript:,
    data:, vbscript:, file: — in one place, instead of trusting each of the ten templates that
    render a URL to guard itself. `detail.html` shows why per-template guards fail: it checked
    `'http' in link`, which `javascript:alert("http")` passes.

    Anything rejected becomes "#", so the card still renders and stays clickable-looking rather than
    silently vanishing.
    """
    text = (value or "").strip()
    low = text.lower()
    if low.startswith(("http://", "https://")):
        return text
    if text.startswith("/") and not text.startswith("//"):  # site-relative; // is protocol-relative
        return text
    return "#"


templates.env.globals["card_image"] = cards.card_image  # used by the shared _card.html macro
templates.env.globals["sync_status"] = sync_status
templates.env.globals["is_new"] = is_new
# The per-item clock: `ago` prints "4h ago", `stamp` the absolute date behind it on hover.
# Both return None when a source gave us no date, and the templates then print nothing —
# an undated item must never be able to look fresh.
templates.env.globals["ago"] = freshness.ago
templates.env.globals["stamp"] = freshness.stamp
templates.env.filters["safe_url"] = safe_url
app.mount("/static", StaticFiles(directory=str(BASE_DIR.parent / "static")), name="static")


@app.middleware("http")
async def gate(request: Request, call_next):
    """One shared-secret gate over the WHOLE app. Off when INGEST_TOKEN is unset; when set, every
    route except /health and /static needs the token (X-Ingest-Token header for the iOS Shortcut,
    or HTTP Basic Auth for a browser). A miss returns 401 with a Basic-Auth challenge so the
    browser prompts for the password — keeps the corpus private once the app is tunnelled."""
    if not auth.is_exempt(request.url.path) and not auth.is_authorized(
        request.headers.get("x-ingest-token"), request.headers.get("authorization")
    ):
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="get-your-knowledge-right"'},
        )
    return await call_next(request)


URL_RE = re.compile(r"https?://[^\s\"']+")


class IngestRequest(BaseModel):
    url: str  # may arrive as messy share-sheet text; we extract the real URL below


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.post("/ingest", status_code=202)
def ingest(payload: IngestRequest, background_tasks: BackgroundTasks) -> dict[str, object]:
    """Pull the URL out of whatever was shared, store it, then process in the background."""
    match = URL_RE.search(payload.url)
    if not match:
        raise HTTPException(status_code=422, detail="no URL found in shared content")
    reel = store.save_reel(Reel(url=match.group(0)))
    background_tasks.add_task(process_reel, reel.id)  # respond instantly; process after responding
    return {"id": reel.id, "status": "accepted"}


@app.get("/thumb/{reel_id}")
def thumb(reel_id: int) -> FileResponse:
    """Serve a reel's locally-saved cover frame (we proxy it because IG's CDN blocks hotlinking)."""
    path = THUMB_DIR / f"{reel_id}.jpg"
    if not path.exists():
        raise HTTPException(status_code=404, detail="no thumbnail")
    return FileResponse(path, media_type="image/jpeg")


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    """The command center: signal + lanes + a live stream across every source + saved + reels,
    all on one screen (the JARVIS terminal)."""
    profile = load_profile()
    corpus = store.list_all_radar()
    avoid = lanes.avoid_terms(profile)
    lane_rows = [
        {
            "idx": idx,
            "name": name,
            "count": len(lanes.curate(corpus, topics, limit=500, avoid=avoid)),
        }
        for idx, (name, topics) in enumerate(lanes.lanes_from_profile(profile))
    ]
    signal = lanes.pulse(corpus, profile, top=8)
    smax = max((s["mentions"] for s in signal), default=1) or 1
    for s in signal:
        s["pct"] = max(8, round(s["mentions"] / smax * 100))  # min 8% so the bar is always visible
    return templates.TemplateResponse(
        request,
        "terminal.html",
        {
            "signal": signal,
            "lanes": lane_rows,
            # Opportunities lead the page: everything else is reading, this is the part you can
            # ENTER. store.list_radar already sorts by score, which for opps is relevance+deadline.
            "opps": store.list_radar("opps")[:6],
            "stream": corpus[:40],
            "saved": store.list_saved(),
            "reels": store.list_recent(limit=8),
        },
    )


@app.get("/reels", response_class=HTMLResponse)
def reels_dashboard(request: Request) -> HTMLResponse:
    """The reels gallery, newest first."""
    return templates.TemplateResponse(request, "dashboard.html", {"reels": store.list_recent()})


@app.get("/github", response_class=HTMLResponse)
def github_tab(request: Request) -> HTMLResponse:
    """The GitHub radar tab: what's trending RIGHT NOW first, then the top repos in your topics.
    Fresh leads established — a tool released last week is the thing you'd have missed."""
    return templates.TemplateResponse(
        request,
        "github.html",
        {"items": store.list_radar("trending") + store.list_radar("github")},
    )


@app.post("/github/refresh")
def github_refresh() -> RedirectResponse:
    """Pull both halves — trending now, plus repos for your topics. Refreshed independently so a
    rate-limited search can't wipe the trending list (or the reverse)."""
    profile = load_profile()
    refresh_source("trending", github_radar.fetch_trending)
    refresh_source("github", lambda: github_radar.fetch_repos(profile))
    return RedirectResponse(url="/github", status_code=303)


@app.get("/hn", response_class=HTMLResponse)
def hn_tab(request: Request) -> HTMLResponse:
    """The Hacker News radar tab: top stories matching the user's focus topics."""
    return templates.TemplateResponse(request, "hackernews.html", {"items": store.list_radar("hn")})


@app.post("/hn/refresh")
def hn_refresh() -> RedirectResponse:
    """Pull a fresh batch of stories and replace the stored HN radar, then show the tab."""
    items = hn_radar.fetch_stories(load_profile())
    store.replace_radar("hn", items)
    return RedirectResponse(url="/hn", status_code=303)


@app.get("/reddit", response_class=HTMLResponse)
def reddit_tab(request: Request) -> HTMLResponse:
    """The Reddit radar tab. Dormant (shows a setup hint) until the app creds are in .env."""
    return templates.TemplateResponse(
        request,
        "reddit.html",
        {"items": store.list_radar("reddit"), "configured": reddit_radar.has_credentials()},
    )


@app.post("/reddit/refresh")
def reddit_refresh() -> RedirectResponse:
    """Pull a fresh batch of posts and replace the stored Reddit radar, then show the tab."""
    if reddit_radar.has_credentials():
        try:
            store.replace_radar("reddit", reddit_radar.fetch_posts(load_profile()))
        except reddit_radar.RadarError:
            pass  # bad creds / rate limit — keep what we had, the tab still renders
    return RedirectResponse(url="/reddit", status_code=303)


@app.get("/ideas", response_class=HTMLResponse)
def ideas_view(request: Request, generating: int = 0) -> HTMLResponse:
    """The Idea Space: synthesized opportunities (build / paper) to accept or reject. Accepted ideas
    are the shortlist; new ones await your call. This is where information becomes knowledge."""
    return templates.TemplateResponse(
        request,
        "ideas.html",
        {
            "active_tab": "ideas",
            "generating": bool(generating),
            "new_ideas": [_idea_ctx(i) for i in store.list_ideas("new")],
            "accepted": [_idea_ctx(i) for i in store.list_ideas("accepted")],
        },
    )


def _generate_ideas() -> None:
    """Synthesize a fresh batch of ideas from the corpus and store them. Best-effort: a NIM failure
    or timeout is logged, not raised (it runs in the background after the response is sent)."""
    try:
        ideas = synthesize.synthesize_ideas(store.list_all_radar(), load_profile())
    except Exception:  # noqa: BLE001 — synthesis is best-effort; the page just shows nothing new
        logging.warning("idea synthesis failed", exc_info=True)
        return
    if ideas:
        store.add_ideas(ideas)


@app.post("/ideas/generate")
def ideas_generate(background_tasks: BackgroundTasks) -> RedirectResponse:
    """Kick off synthesis in the background (NIM is slow) and return instantly to the triage page,
    which polls until the new ideas land."""
    background_tasks.add_task(_generate_ideas)
    return RedirectResponse(url="/ideas?generating=1", status_code=303)


@app.post("/ideas/{idea_id}/accept")
def idea_accept(idea_id: int) -> RedirectResponse:
    """Keep an idea on the shortlist to go deep on later."""
    store.set_idea_status(idea_id, "accepted")
    return RedirectResponse(url="/ideas", status_code=303)


@app.post("/ideas/{idea_id}/reject")
def idea_reject(idea_id: int) -> RedirectResponse:
    """Dismiss an idea — it drops out of the triage list."""
    store.set_idea_status(idea_id, "rejected")
    return RedirectResponse(url="/ideas", status_code=303)


def _idea_ctx(idea) -> dict:
    """Template shape for one idea: the row plus its decoded source list."""
    return {"idea": idea, "sources": _load_json_list(idea.sources)}


@app.get("/idea/{idea_id}", response_class=HTMLResponse)
def idea_detail(request: Request, idea_id: int) -> HTMLResponse:
    """One idea, expanded: the pattern, the plan, its sources, and — once generated — the deep dive
    (the full actionable plan). The deep dive is generated on demand via the button below."""
    idea = store.get_idea(idea_id)
    if idea is None:
        raise HTTPException(status_code=404, detail="idea not found")
    return templates.TemplateResponse(
        request, "idea_detail.html", {"active_tab": "ideas", **_idea_ctx(idea)}
    )


@app.post("/idea/{idea_id}/deepen")
def idea_deepen(idea_id: int) -> RedirectResponse:
    """Generate the full actionable plan for this idea and cache it, then show the detail page."""
    idea = store.get_idea(idea_id)
    if idea is not None and not idea.depth:
        try:
            store.set_idea_depth(idea_id, synthesize.deepen_idea(idea, load_profile()))
        except Exception:  # noqa: BLE001 — best-effort; the page still shows the idea + a retry
            logging.warning("idea deepen failed", exc_info=True)
    return RedirectResponse(url=f"/idea/{idea_id}", status_code=303)


@app.get("/lanes", response_class=HTMLResponse)
def lanes_overview(request: Request) -> HTMLResponse:
    """Curated home: each of your aspects (lanes) with its top items pulled across ALL sources."""
    profile = load_profile()
    corpus = store.list_all_radar()
    avoid = lanes.avoid_terms(profile)
    blocks = [
        {
            "idx": idx,
            "name": name,
            "picks": lanes.curate(corpus, topics, limit=6, avoid=avoid),
            "signal": lanes.lane_signal(corpus, topics),
        }
        for idx, (name, topics) in enumerate(lanes.lanes_from_profile(profile))
    ]
    return templates.TemplateResponse(request, "lanes.html", {"lanes": blocks})


@app.get("/pulse", response_class=HTMLResponse)
def pulse_view(request: Request) -> HTMLResponse:
    """The cross-lane pulse: what's heating up across your whole spectrum right now, ranked."""
    hot = lanes.pulse(store.list_all_radar(), load_profile())
    return templates.TemplateResponse(request, "pulse.html", {"hot": hot})


@app.get("/search", response_class=HTMLResponse)
def search(request: Request, q: str = "") -> HTMLResponse:
    """Free-text search across the WHOLE corpus, every source at once, ranked by relevance."""
    results = lanes.search_corpus(store.list_all_radar(), q) if q.strip() else []
    return templates.TemplateResponse(request, "search.html", {"q": q, "results": results})


def _back(request: Request, default: str = "/saved") -> str:
    """Where to send the user after a save/unsave: back to the page they were on (same-host
    Referer), else a safe default. Guards against an off-site open redirect."""
    ref = request.headers.get("referer") or ""
    host = request.headers.get("host") or ""
    return ref if (ref and host and f"//{host}" in ref) else default


@app.post("/save")
def save_item(request: Request, item_id: int = Form(...)) -> RedirectResponse:
    """Keep a radar item on the shortlist (idempotent), then return to where you were."""
    store.save_radar(item_id)
    return RedirectResponse(url=_back(request), status_code=303)


@app.post("/unsave")
def unsave_item(request: Request, url: str = Form(...)) -> RedirectResponse:
    """Drop an item from the shortlist, then return to where you were."""
    store.unsave(url)
    return RedirectResponse(url=_back(request), status_code=303)


@app.get("/saved", response_class=HTMLResponse)
def saved_view(request: Request) -> HTMLResponse:
    """Your curated shortlist — the items you decided are worth acting on, newest first."""
    return templates.TemplateResponse(request, "saved.html", {"items": store.list_saved()})


@app.get("/lane/{idx}", response_class=HTMLResponse)
def lane_detail(request: Request, idx: int) -> HTMLResponse:
    """One aspect, expanded: what's heating up in it (signal) + every matching item across sources.
    The signal reads the same corpus we curate — no new fetch."""
    profile = load_profile()
    defs = lanes.lanes_from_profile(profile)
    if idx < 0 or idx >= len(defs):
        raise HTTPException(status_code=404, detail="lane not found")
    name, topics = defs[idx]
    corpus = store.list_all_radar()
    items = lanes.curate(corpus, topics, limit=50, avoid=lanes.avoid_terms(profile))
    signal = lanes.lane_signal(corpus, topics, top=10)  # focused view shows more than the overview
    return templates.TemplateResponse(
        request, "lane.html", {"name": name, "idx": idx, "items": items, "signal": signal}
    )


def refresh_source(source: str, fetch, eng=None) -> bool:
    """Pull one radar source and swap its fresh batch into the corpus — but ONLY if the fetch
    actually returned items. A transient failure (network/parse/rate-limit like arXiv's 429) comes
    back empty or raises; either way we KEEP the data we already have instead of wiping the source
    to nothing. Isolated per source so one bad fetch never sinks a batch refresh. Returns whether
    the corpus was updated."""
    try:
        items = fetch()
    except Exception:  # noqa: BLE001 — a single bad source must not break the whole refresh
        logging.warning("radar refresh: source %r failed", source, exc_info=True)
        return False
    if not items:
        logging.warning("radar refresh: source %r returned nothing; kept existing items", source)
        return False
    store.replace_radar(source, items, eng)
    return True


PREWARM_COUNT = 6  # how many newest items to analyze in the background after a SYNC


def _prewarm_top(n: int = PREWARM_COUNT) -> None:
    """Analyze the newest n radar items that aren't analyzed yet, so the likely clicks open
    instantly. Best-effort and sequential (gentle on the NIM free tier); _analyze_and_cache
    swallows per-item failures."""
    for item in store.list_all_radar(limit=n):
        if not item.overview:
            _analyze_and_cache(item)


def refresh_everything(profile: dict | None = None, eng=None) -> dict[str, bool]:
    """Pull every source into the corpus. Returns {source: was_updated} so a caller can report what
    actually landed — a click can redirect and show it, the scheduler can log it.

    Deliberately free of any request/response handling: this is the whole job, callable from a
    route, from the 6-hourly heartbeat, or from a test with no HTTP layer at all."""
    profile = load_profile() if profile is None else profile
    # Every per-topic source (github/hn/gnews/arxiv) searches EVERY lane's topics, so the thin
    # lanes (Web Design, Jobs) fill from all of them, not just the focus line. fetch_repos self-caps
    # the topics it searches to GitHub's rate limit (~10 unauth / ~30 with a token) so a SYNC never
    # 429s its tail and shrinks the github corpus. news (rss) has fixed feeds — it ranks, no search.
    lane_topics = lanes.search_topics(profile)
    results = {
        "trending": refresh_source("trending", github_radar.fetch_trending, eng),
        "github": refresh_source(
            "github", lambda: github_radar.fetch_repos(profile, topics=lane_topics), eng
        ),
        "hn": refresh_source(
            "hn", lambda: hn_radar.fetch_stories(profile, topics=lane_topics), eng
        ),
        "news": refresh_source("news", lambda: rss_radar.fetch_news(profile), eng),
        "arxiv": refresh_source(
            "arxiv", lambda: arxiv_radar.fetch_papers(profile, topics=lane_topics), eng
        ),
        "gnews": refresh_source(
            "gnews", lambda: gnews_radar.fetch_news(profile, topics=lane_topics), eng
        ),
        "opps": refresh_source(
            "opps", lambda: opportunity_radar.fetch_opportunities(profile, lane_topics), eng
        ),
        # YC's Requests for Startups: not "what exists" but "what the people writing cheques want
        # built". A dozen items that change a few times a year — cheap to pull, and the only source
        # that states demand rather than supply.
        "ycrfs": refresh_source("ycrfs", lambda: yc_rfs.fetch_yc_rfs(profile, lane_topics), eng),
    }
    if reddit_radar.has_credentials():
        results["reddit"] = refresh_source("reddit", lambda: reddit_radar.fetch_posts(profile), eng)
    return results


@app.post("/refresh-all")
def refresh_all(background_tasks: BackgroundTasks) -> RedirectResponse:
    """Pull every source at once into the corpus, then show the curated lanes. Each source is
    isolated (refresh_source) so one failing or empty fetch never wipes or sinks the others.
    After the fetches, pre-warm the newest items' analysis in the background."""
    # Recorded like a scheduled beat so a manual SYNC also moves the "last synced" clock and the
    # NEW cutoff — otherwise clicking SYNC would leave the header claiming the corpus was stale.
    run_id = store.start_sync(trigger="manual")
    store.finish_sync(run_id, refresh_everything())
    background_tasks.add_task(_prewarm_top)  # warm the newest items after responding
    return RedirectResponse(url="/lanes", status_code=303)


@app.get("/opps", response_class=HTMLResponse)
def opps_tab(request: Request) -> HTMLResponse:
    """Things you can ENTER: open hackathons, soonest-and-most-relevant deadline first. The one
    tab that produces output instead of more reading."""
    return templates.TemplateResponse(request, "opps.html", {"items": store.list_radar("opps")})


@app.post("/opps/refresh")
def opps_refresh(background_tasks: BackgroundTasks) -> RedirectResponse:
    """Pull a fresh batch of open hackathons, replace the stored list, then show the tab."""
    profile = load_profile()
    store.replace_radar(
        "opps", opportunity_radar.fetch_opportunities(profile, lanes.search_topics(profile))
    )
    background_tasks.add_task(_prewarm_top, 4)  # warm the top hackathons for instant clicks
    return RedirectResponse(url="/opps", status_code=303)


@app.get("/ycrfs", response_class=HTMLResponse)
def ycrfs_tab(request: Request) -> HTMLResponse:
    """What YC is asking founders to build right now — demand, not supply. Ranked by how well each
    request matches your topics, since a request in your field is the one you could answer."""
    return templates.TemplateResponse(request, "ycrfs.html", {"items": store.list_radar("ycrfs")})


@app.post("/ycrfs/refresh")
def ycrfs_refresh() -> RedirectResponse:
    """Re-read YC's RFS page and replace the stored list, then show the tab."""
    profile = load_profile()
    store.replace_radar("ycrfs", yc_rfs.fetch_yc_rfs(profile, lanes.search_topics(profile)))
    return RedirectResponse(url="/ycrfs", status_code=303)


@app.get("/news", response_class=HTMLResponse)
def news_tab(request: Request) -> HTMLResponse:
    """The news radar tab: recent tech-news + lab/vendor RSS items, ranked by your topics."""
    return templates.TemplateResponse(request, "news.html", {"items": store.list_radar("news")})


@app.post("/news/refresh")
def news_refresh() -> RedirectResponse:
    """Pull a fresh batch from the RSS feeds, replace the stored news radar, then show the tab."""
    store.replace_radar("news", rss_radar.fetch_news(load_profile()))
    return RedirectResponse(url="/news", status_code=303)


def _save_breakdown(item, data: dict) -> None:
    """Cache an analysis result's fields onto a radar item (builds/product_ideas as JSON)."""
    item.overview = data.get("overview", "")
    item.usage = data.get("usage", "")
    item.builds = json.dumps(data.get("builds") or [])
    item.product_ideas = json.dumps(data.get("product_ideas") or [])
    store.save_radar_item(item)


def _breakdown_ctx(item) -> dict:
    """Template context for rendering a radar item's cached breakdown."""
    return {
        "item": item,
        "builds": _load_json_list(item.builds),
        "product_ideas": _load_json_list(item.product_ideas),
    }


@app.get("/github/{item_id}", response_class=HTMLResponse)
def github_detail(request: Request, item_id: int) -> HTMLResponse:
    """A repo's breakdown: overview, usage, builds, product ideas. Analyzed once, then cached."""
    item = store.get_radar_item(item_id)
    if item is None or item.source != "github":
        raise HTTPException(status_code=404, detail="repo not found")
    if not item.overview:  # not analyzed yet → do it once, then cache
        try:
            _save_breakdown(item, github_radar.analyze_repo(item, load_profile()))
        except Exception:  # noqa: BLE001 — analysis is best-effort; still show the repo
            pass
    return templates.TemplateResponse(request, "github_detail.html", _breakdown_ctx(item))


def _analyze_and_cache(item) -> None:
    """Two-pass analysis cached on the item: analyst draft -> critic refine (a second agent judging
    the first, for real depth). Best-effort — a draft survives if the refine fails, and a total
    failure just leaves overview empty (the page shows a fallback)."""
    profile = load_profile()
    try:
        if item.source in github_radar.REPO_SOURCES:
            draft = github_radar.analyze_repo(item, profile)
        elif item.source == "opps":
            draft = opportunity_radar.analyze_opportunity(item, profile)
        else:
            draft = research.analyze_item(item, profile)
    except Exception:  # noqa: BLE001 — analysis is best-effort
        return
    signal = last30days_bridge.fetch_signal(item.title)  # best-effort; None on any failure
    try:
        data = research.refine_analysis(item, profile, draft, signal=signal)
    except Exception:  # noqa: BLE001 — the critic pass is a bonus; keep the draft
        data = draft
    _save_breakdown(item, data)


@app.get("/item/{item_id}", response_class=HTMLResponse)
def item_detail(request: Request, item_id: int) -> HTMLResponse:
    """Opens INSTANTLY. If the depth isn't cached yet, the page shows a spinner and fetches
    /item/{id}/analysis in the background — so the click never hangs the tab on the NIM call."""
    item = store.get_radar_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    return templates.TemplateResponse(
        request, "item_detail.html", {**_breakdown_ctx(item), "analyzed": bool(item.overview)}
    )


@app.get("/item/{item_id}/analysis", response_class=HTMLResponse)
def item_analysis(request: Request, item_id: int) -> HTMLResponse:
    """The depth read as an HTML fragment — generated two-pass on first request, then cached.
    The detail page fetches this so the click is instant."""
    item = store.get_radar_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    if not item.overview:
        _analyze_and_cache(item)
    return templates.TemplateResponse(request, "_analysis.html", _breakdown_ctx(item))


@app.get("/reel/{reel_id}", response_class=HTMLResponse)
def reel_detail(request: Request, reel_id: int) -> HTMLResponse:
    """Full breakdown for one reel: take, summary, links, transcript."""
    reel = store.get_reel(reel_id)
    if reel is None:
        raise HTTPException(status_code=404, detail="reel not found")
    links = _load_json_list(reel.tools_links)
    takeaways = _load_json_list(reel.key_takeaways)
    repo = find_repo(reel)  # does this reel mention a GitHub repo?
    repo_item = (
        store.find_or_create_github_item(repo[0], repo[1]) if repo else None
    )  # reuse/create its radar entry so we can link to its breakdown page
    return templates.TemplateResponse(
        request,
        "detail.html",
        {"reel": reel, "links": links, "takeaways": takeaways, "repo_item": repo_item},
    )


def _load_json_list(raw: str | None) -> list[str]:
    """Decode a JSON-encoded list column, tolerating null/garbage."""
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []
