"""FastAPI app: ingest webhook + dashboard. The pipeline behind /ingest is stubbed in v1's
walking skeleton; real stages swap in across Tasks 4-6."""

import json
import re
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app import store
from app.ingest import process_reel
from app.models import Reel

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


@app.get("/reel/{reel_id}", response_class=HTMLResponse)
def reel_detail(request: Request, reel_id: int) -> HTMLResponse:
    """Full breakdown for one reel: take, summary, links, transcript."""
    reel = store.get_reel(reel_id)
    if reel is None:
        raise HTTPException(status_code=404, detail="reel not found")
    links: list[str] = []
    if reel.tools_links:
        try:
            links = json.loads(reel.tools_links)
        except json.JSONDecodeError:
            links = []
    return templates.TemplateResponse(request, "detail.html", {"reel": reel, "links": links})
