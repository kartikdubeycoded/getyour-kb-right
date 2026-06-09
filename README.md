# get-your-knowledge-right

**Turn the reels you save into knowledge you actually use.**

Share an Instagram reel to the app and it *understands* it — hearing the audio, reading the
caption, and seeing the on-screen text — then researches what it's about and surfaces it on a
dashboard with a summary, key takeaways, the tools/links it mentions, whether you could **build**
something from it, and a *do this / skip this* take tailored to your focus. Alongside reels, a
**tech radar** pulls what's trending in your topics from GitHub, Hacker News, and Reddit — so your
saved reels stop disappearing into your DMs unread and you stay on top of where your field is moving.

## How it works

```
share reel URL → /ingest → download (yt-dlp) → hear (faster-whisper) + read (caption) + see (vision)
              → research (LLM) → store (SQLite) → dashboard
```

Reels that mention a GitHub repo link straight to that repo's breakdown, so the radar becomes a
curated hub fed by both your reels and your topic searches.

Ingestion is ToS-safe: you share a **public** reel's link (e.g. via an iOS Shortcut that POSTs to
`/ingest`). Every source uses an official API — no scraping, no login.

## Stack

- Python · FastAPI · SQLite (SQLModel) · Jinja2
- **Transcription:** local `faster-whisper` (free, no API key)
- **Research + vision:** an LLM via an OpenAI-compatible endpoint (free NVIDIA NIM by default),
  behind a small interface so any provider can be swapped in
- **Tech radar:** official APIs only — GitHub Search, the Hacker News (Algolia) Search API, and the
  Reddit OAuth API

## Status

v1 works end-to-end: share a reel → it's downloaded, transcribed, read, seen, researched, and shown
with a personalized take and a buildable verdict. The tech radar is live for GitHub and Hacker News;
Reddit is wired and activates once you add free app credentials.

## Run it (dev)

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  ·  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open <http://localhost:8000>, then add a reel:

```bash
curl -X POST localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d "{\"url\": \"https://www.instagram.com/reel/XXXX/\"}"
```

Research uses a free NVIDIA NIM key (build.nvidia.com) set as `NVIDIA_API_KEY` once that stage lands.

## Run it (Docker)

```bash
cp .env.example .env
# edit .env: set NVIDIA_API_KEY; set INGEST_TOKEN before exposing this outside localhost
docker compose up --build
```

Open <http://localhost:8000>. Docker stores the SQLite database and downloaded media in the
`gykr-data` volume. The image uses `profile.example.yaml` by default; edit that before building if
you want a custom focus profile inside the container.

## Tests

```bash
pytest -q
```

## Roadmap

- **v1** — share → hear/read/see → research → dashboard ✓
- **Tech radar** — trending tools and ideas from your sources (GitHub ✓ · Hacker News ✓ · Reddit ✓) 
- **Cross-source signal** — read across the sources to surface where your field is turning
- **Batch player** — play a shared set of reels in order
- **One-click deploy** — `docker compose up` for a ready-to-run instance
