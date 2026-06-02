"""FastAPI app: ingest webhook + dashboard. The pipeline behind /ingest is stubbed in v1's
walking skeleton; real stages swap in across Tasks 4-6."""

import json
import re
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app import github_radar, store
from app.ingest import process_reel
from app.models import Reel
from app.profile import load_profile

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
    return templates.TemplateResponse(
        request, "detail.html", {"reel": reel, "links": links, "takeaways": takeaways}
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
