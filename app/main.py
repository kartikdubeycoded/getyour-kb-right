"""FastAPI app: ingest webhook + dashboard. The pipeline behind /ingest is stubbed in v1's
walking skeleton; real stages swap in across Tasks 4-6."""

from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, HttpUrl

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


class IngestRequest(BaseModel):
    url: HttpUrl


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.post("/ingest", status_code=202)
def ingest(payload: IngestRequest) -> dict[str, object]:
    """Accept a reel URL, store it, run the (stubbed) pipeline. Returns the new reel id."""
    reel = store.save_reel(Reel(url=str(payload.url)))
    process_reel(reel.id)  # inline for the skeleton; becomes a background task in Task 7
    return {"id": reel.id, "status": "accepted"}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    """Render processed reels, newest first."""
    return templates.TemplateResponse(
        request, "dashboard.html", {"reels": store.list_recent()}
    )
