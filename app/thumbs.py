"""Download a reel's cover frame to our OWN server so the browser can show it. Instagram's CDN
blocks hotlinking and signs/expires its image URLs, so an <img> pointing straight at it fails. We
fetch the bytes server-side (same browser User-Agent the vision model uses to beat the CDN) and
save them locally; the page then loads them from /thumb/{id} on our own origin."""

import os
import urllib.request
from pathlib import Path

THUMB_DIR = Path(os.getenv("MEDIA_DIR", "media")) / "thumbs"  # under media/ (gitignored)
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124"


def save_thumbnail(url: str | None, reel_id: int) -> str | None:
    """Fetch the cover frame and save it as media/thumbs/{reel_id}.jpg. Returns the local path the
    browser requests (/thumb/{id}), or None on any failure — the thumbnail is best-effort."""
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})  # CDNs 403 the default UA
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 (public CDN image)
            data = resp.read()
        THUMB_DIR.mkdir(parents=True, exist_ok=True)
        (THUMB_DIR / f"{reel_id}.jpg").write_bytes(data)
        return f"/thumb/{reel_id}"
    except Exception:  # noqa: BLE001 — thumbnail must never break the pipeline
        return None
