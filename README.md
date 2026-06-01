# get-your-knowledge-right

**Turn the reels you save into knowledge you actually use.**

Share an Instagram reel to the app and it downloads the video, transcribes the audio, researches
what it's about, and surfaces it on a dashboard with a short summary, the tools/links it mentions,
and a *do this / skip this* take tailored to your focus — so the reels you bookmark stop
disappearing into your DMs unread.

## How it works

```
share reel URL → /ingest → download (yt-dlp) → transcribe (faster-whisper)
              → research (LLM) → store (SQLite) → dashboard
```

Ingestion is ToS-safe: you share a **public** reel's link (e.g. via an iOS Shortcut that POSTs to
`/ingest`). No scraping, no login.

## Stack

- Python · FastAPI · SQLite (SQLModel) · Jinja2
- **Transcription:** local `faster-whisper` (free, no API key)
- **Research:** an LLM via an OpenAI-compatible endpoint (free NVIDIA NIM by default), behind a small
  interface so any provider can be swapped in

## Status

v1 in progress. The end-to-end skeleton works (ingest → store → dashboard); the real download,
transcription, and research stages are being wired in.

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

## Tests

```bash
pytest -q
```

## Roadmap

- **v1** — share → transcribe → research → dashboard
- **Tech radar** — a daily digest of new tools and ideas from across your sources
- **Batch player** — play a shared set of reels in order
- **One-click deploy** — `docker compose up` for a ready-to-run instance
