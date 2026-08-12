# get-your-knowledge-right

**A personal knowledge engine: turn the firehose you already read into decisions you actually act on.**

It watches the places your field moves — repos, papers, news, launches, discussion, open hackathons —
ranks it all against *your* topics, reads across sources to propose things worth building, and pushes
a digest to your phone. It also ingests reels you share, so the links you save stop dying in your DMs.

The point isn't more to read. It's **less to read and something to do.**

---

## What it does

**1. Watches (the radar).** Nine sources on a 6-hourly self-refresh, every item scored against your
focus topics:

| source | what it answers | key needed |
|---|---|---|
| `trending` | a new repo just dropped | — |
| `github` | what's being built in my topics | optional (raises rate limit) |
| `hn` | what practitioners are arguing about | — |
| `news` | 20 RSS feeds: press, labs, VCs, practitioners | — |
| `gnews` | topic-targeted news search | — |
| `arxiv` | what research just landed | — |
| `opps` | **hackathons I can still enter**, with deadlines | — |
| `ycrfs` | **what YC is asking founders to build** | — |
| `reddit` | community discussion | optional (dormant until set) |
| `reels` | reels you share, transcribed + researched | — |

Most sources answer *"what exists."* `opps` and `ycrfs` are different on purpose: they answer
*"what can I do,"* and *"what does someone with money want built."* Those are the ones that produce
output instead of more input.

**2. Curates (lanes).** Your profile defines *aspects* — AI/ML, Web Design, Systems, your own live
projects. Each lane scores the **whole corpus** across every source, so a lane is a view, not another
feed. Each lane also shows what's *heating up* across sources.

**3. Synthesizes (the Idea Space).** The part that turns information into knowledge. It reads across
2+ unrelated sources, finds the gap between them, and proposes concrete **build** or **paper** ideas
you accept or reject — then deepens an accepted one into a real plan (stack, pieces, first week).

**4. Tells you (push).** After each sync, a Telegram digest: new ideas, hackathons closing soonest,
and what actually got published since you last looked.

## How a reel flows

```
share reel URL → /ingest → download (yt-dlp)
               → hear (whisper) + read (caption) + see (vision)
               → research (LLM) → SQLite → dashboard
```

Ingestion is ToS-safe: you share a **public** reel's link (an iOS Shortcut POSTing to `/ingest` works
well). Every source uses an official API, a public feed, or a published page — no scraping, no login,
no automation of anyone's account.

## Stack

- Python · FastAPI · SQLite (SQLModel) · Jinja2
- **LLM:** provider-agnostic behind one interface — `groq` (default), `deepseek`, `qwen`, or `nim`.
  Swap engines with one line in `.env`; every call site goes through `make_llm()`.
- **Transcription:** local `faster-whisper` (free, no key), or Groq for a lighter container.
- **Self-refresh:** an in-process scheduler. Honest limitation — it cannot refresh while the machine
  is off, so the header states when it last synced rather than implying continuous coverage.

## Run it (dev)

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  ·  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp .env.example .env            # set one LLM key (GROQ_API_KEY is the easiest free start)
uvicorn app.main:app --reload
```

Open <http://localhost:8000>, hit **SYNC** to fill the corpus, then add a reel:

```bash
curl -X POST localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d "{\"url\": \"https://www.instagram.com/reel/XXXX/\"}"
```

Copy `profile.example.yaml` to `profile.yaml` (gitignored) and edit it — it drives the ranking, the
lanes, and the personalized take.

## Run it (Docker)

```bash
cp .env.example .env            # set your LLM key
docker compose up --build
```

Data (SQLite + media) persists in the `gykr-data` volume.

## Security

- **The app is unauthenticated by default**, which is fine on localhost and *not* fine anywhere else.
  Set `INGEST_TOKEN` **before** exposing it beyond your own machine — it gates every route except
  `/health` and `/static`, via the `X-Ingest-Token` header (for a Shortcut) or HTTP Basic Auth
  (for a browser). Generate one with:
  `python -c "import secrets;print(secrets.token_urlsafe(32))"`
- `docker-compose.yml` publishes on **loopback only**. To serve other machines, set `INGEST_TOKEN`
  first, *then* widen the binding — in that order.
- Item URLs come from third-party feeds and are never ours, so every rendered link target is passed
  through a scheme allowlist (`http`/`https`/site-relative). Escaping alone does not stop a
  `javascript:` URL from executing on click.
- Secrets live in `.env` (gitignored) and are never committed.

## Tests

```bash
pytest -q          # 213 tests
ruff check .
pip-audit          # dependency CVEs; also runs in CI
```

## Roadmap

- **v1 — reels** — share → hear/read/see → research → dashboard ✓
- **Radar** — repos · HN · news · Google News · arXiv · trending · hackathons · YC RFS ✓
- **Lanes + cross-source signal** — what's heating up per aspect ✓
- **Idea Space** — synthesis into build/paper ideas you can accept and deepen ✓
- **Push** — Telegram digest after each sync ✓
- **Always-on** — run it somewhere that doesn't sleep, so the radar never goes stale
- **Batch player** — play a shared set of reels in order
