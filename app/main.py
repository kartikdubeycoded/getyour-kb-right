"""FastAPI app: ingest webhook + dashboard. The pipeline behind /ingest is stubbed in v1's
walking skeleton; real stages swap in across Tasks 4-6."""

import json
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app import (
    arxiv_radar,
    github_radar,
    gnews_radar,
    hn_radar,
    lanes,
    reddit_radar,
    rss_radar,
    store,
)
from app.ingest import process_reel
from app.models import Reel
from app.profile import load_profile
from app.repo_link import find_repo
from app.thumbs import THUMB_DIR

BASE_DIR = Path(__file__).resolve().parent

load_dotenv()  # read .env in dev (NVIDIA_API_KEY etc.)


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init_db()
    yield


app = FastAPI(title="get-your-knowledge-right", lifespan=lifespan)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR.parent / "static")), name="static")


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
def dashboard(request: Request) -> HTMLResponse:
    """Render processed reels, newest first."""
    return templates.TemplateResponse(
        request, "dashboard.html", {"reels": store.list_recent()}
    )


@app.get("/github", response_class=HTMLResponse)
def github_tab(request: Request) -> HTMLResponse:
    """The GitHub radar tab: top repos in the user's focus topics."""
    return templates.TemplateResponse(
        request, "github.html", {"items": store.list_radar("github")}
    )


@app.post("/github/refresh")
def github_refresh() -> RedirectResponse:
    """Pull a fresh batch of repos and replace the stored GitHub radar, then show the tab."""
    items = github_radar.fetch_repos(load_profile())
    store.replace_radar("github", items)
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


@app.get("/lanes", response_class=HTMLResponse)
def lanes_overview(request: Request) -> HTMLResponse:
    """Curated home: each of your aspects (lanes) with its top items pulled across ALL sources."""
    profile = load_profile()
    corpus = store.list_all_radar()
    avoid = lanes.avoid_terms(profile)
    blocks = [
        {"idx": idx, "name": name, "picks": lanes.curate(corpus, topics, limit=6, avoid=avoid)}
        for idx, (name, topics) in enumerate(lanes.lanes_from_profile(profile))
    ]
    return templates.TemplateResponse(request, "lanes.html", {"lanes": blocks})


@app.get("/lane/{idx}", response_class=HTMLResponse)
def lane_detail(request: Request, idx: int) -> HTMLResponse:
    """One aspect, expanded: every matching item across sources, best match first."""
    profile = load_profile()
    defs = lanes.lanes_from_profile(profile)
    if idx < 0 or idx >= len(defs):
        raise HTTPException(status_code=404, detail="lane not found")
    name, topics = defs[idx]
    items = lanes.curate(store.list_all_radar(), topics, limit=50, avoid=lanes.avoid_terms(profile))
    return templates.TemplateResponse(
        request, "lane.html", {"name": name, "idx": idx, "items": items}
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


@app.post("/refresh-all")
def refresh_all() -> RedirectResponse:
    """Pull every source at once into the corpus, then show the curated lanes. Each source is
    isolated (refresh_source) so one failing or empty fetch never wipes or sinks the others."""
    profile = load_profile()
    refresh_source("github", lambda: github_radar.fetch_repos(profile))
    refresh_source("hn", lambda: hn_radar.fetch_stories(profile))
    refresh_source("news", lambda: rss_radar.fetch_news(profile))
    refresh_source("arxiv", lambda: arxiv_radar.fetch_papers(profile))
    refresh_source("gnews", lambda: gnews_radar.fetch_news(profile))
    if reddit_radar.has_credentials():
        refresh_source("reddit", lambda: reddit_radar.fetch_posts(profile))
    return RedirectResponse(url="/lanes", status_code=303)


@app.get("/news", response_class=HTMLResponse)
def news_tab(request: Request) -> HTMLResponse:
    """The news radar tab: recent tech-news + lab/vendor RSS items, ranked by your topics."""
    return templates.TemplateResponse(request, "news.html", {"items": store.list_radar("news")})


@app.post("/news/refresh")
def news_refresh() -> RedirectResponse:
    """Pull a fresh batch from the RSS feeds, replace the stored news radar, then show the tab."""
    store.replace_radar("news", rss_radar.fetch_news(load_profile()))
    return RedirectResponse(url="/news", status_code=303)


@app.get("/github/{item_id}", response_class=HTMLResponse)
def github_detail(request: Request, item_id: int) -> HTMLResponse:
    """A repo's breakdown: overview, usage, builds, product ideas. Analyzed once, then cached."""
    item = store.get_radar_item(item_id)
    if item is None or item.source != "github":
        raise HTTPException(status_code=404, detail="repo not found")
    if not item.overview:  # not analyzed yet → do it once, then cache
        try:
            data = github_radar.analyze_repo(item, load_profile())
            item.overview = data.get("overview", "")
            item.usage = data.get("usage", "")
            item.builds = json.dumps(data.get("builds") or [])
            item.product_ideas = json.dumps(data.get("product_ideas") or [])
            store.save_radar_item(item)
        except Exception:  # noqa: BLE001 — analysis is best-effort; still show the repo
            pass
    return templates.TemplateResponse(
        request,
        "github_detail.html",
        {
            "item": item,
            "builds": _load_json_list(item.builds),
            "product_ideas": _load_json_list(item.product_ideas),
        },
    )


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
