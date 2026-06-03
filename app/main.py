"""FastAPI app: ingest webhook + dashboard. The pipeline behind /ingest is stubbed in v1's
walking skeleton; real stages swap in across Tasks 4-6."""

import json
import re
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app import github_radar, hn_radar, store
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
