# Deploy — always-on, fixed URL (Fly.io, Mumbai)

Goal: a permanent `https://<app>.fly.dev/ingest` so the iOS Shortcut works **even when the laptop is
off**, plus the dashboard/ideas always reachable. Runs in Fly's **Mumbai (`bom`)** region.

Why this setup is light + cheap: the deploy uses **Groq** for both transcription (`TRANSCRIBER=groq`)
and analysis (`LLM_PROVIDER=groq`), so there's no local whisper model to download and no big RAM —
a 512 MB machine is plenty. Config is in `fly.toml`; the image is the repo `Dockerfile` (build
verified). `fly deploy` builds on Fly's **remote builders**, so local Docker doesn't need to work.

## What you run (I can't create accounts or log in for you)

### 1. Install the Fly CLI (PowerShell)
```powershell
pwsh -Command "iwr https://fly.io/install.ps1 -useb | iex"
```
Then open a new terminal so `fly` is on PATH.

### 2. Sign up / log in  (needs a card on file; the small machine is a few $/mo)
```powershell
fly auth signup    # or: fly auth login
```

### 3. Create the app from the config (don't deploy yet)
```powershell
fly launch --no-deploy --copy-config --name gykr --region bom
```
If the name `gykr` is taken, pick another and change `app = "..."` at the top of `fly.toml`.

### 4. Set the secrets  (these never go in git or the image)
Run from the project folder so `profile.yaml` is read as-is:
```powershell
fly secrets set GROQ_API_KEY=(Get-Content .env | Select-String '^GROQ_API_KEY=' | ForEach-Object { $_.ToString().Split('=',2)[1] })
fly secrets set INGEST_TOKEN=(-join ((48..57)+(65..90)+(97..122) | Get-Random -Count 40 | ForEach-Object {[char]$_}))
fly secrets set PROFILE_YAML=(Get-Content -Raw profile.yaml)
```
- `GROQ_API_KEY` — your existing key (pulled from `.env`).
- `INGEST_TOKEN` — a fresh 40-char random secret (the line above generates one). **Copy the value**
  `fly secrets list` won't show it back — so print and save it now:
  ```powershell
  fly ssh console -C "printenv INGEST_TOKEN"   # after first deploy; or just save what you set
  ```
  (Easier: set it to a passphrase you choose so you know it: `fly secrets set INGEST_TOKEN=your-long-passphrase`.)
- `PROFILE_YAML` — your real projects/lanes/focus, injected as a secret (never baked into the image).

### 5. Deploy
```powershell
fly deploy --remote-only
fly status          # shows the URL: https://<app>.fly.dev
```

### 6. Point the iOS Shortcut at it
In the Shortcut's **Get Contents of URL** step:
- **URL** → `https://<app>.fly.dev/ingest`
- **Method** → POST
- **Headers** → add `X-Ingest-Token` = your `INGEST_TOKEN`
- **Request Body** (JSON) → `{ "url": "<the shared reel text>" }` (unchanged)

Now sharing a reel hits the always-on server — laptop on or off.

### 7. View the dashboard
Open `https://<app>.fly.dev/` — the browser shows a login box (the token gate). Enter **any
username** and the **`INGEST_TOKEN`** as the password.

## Cost / always-on note
`fly.toml` sets `min_machines_running = 1` so the app is always awake and processes a shared reel
instantly (a few $/mo for one small machine). To save money, set it to `0`: the machine sleeps when
idle and cold-starts on the next request — the reel is still **caught**, but the after-response
processing can be cut short by the sleep. Cost vs. instant — your call.

## Data
SQLite corpus + downloaded media + thumbnails live on the Fly **volume** mounted at `/data`
(`DATABASE_URL`, `MEDIA_DIR`, `THUMB_DIR` in `fly.toml`), so they survive redeploys and restarts.
