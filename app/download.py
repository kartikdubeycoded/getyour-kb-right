"""Download a public reel's audio with yt-dlp. Returns the local audio path; raises DownloadError
on anything yt-dlp can't fetch (private, removed, unsupported, or network error). Audio lands in
media/ (gitignored); faster-whisper (Task 5) decodes it directly — no system ffmpeg needed."""

import os
import uuid
from pathlib import Path

import yt_dlp

MEDIA_DIR = Path(os.getenv("MEDIA_DIR", "media"))


class DownloadError(Exception):
    """yt-dlp could not fetch the URL (private, removed, unsupported, or network issue)."""


def download_audio(url: str, media_dir: Path = MEDIA_DIR) -> Path:
    """Fetch the best audio stream for `url`. Returns the saved file path."""
    media_dir.mkdir(parents=True, exist_ok=True)
    stem = media_dir / uuid.uuid4().hex
    opts = {
        "format": "bestaudio/best",
        "outtmpl": f"{stem}.%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = Path(ydl.prepare_filename(info))
    except Exception as exc:  # yt-dlp raises many types; normalize them to one
        raise DownloadError(str(exc)) from exc
    if not path.exists():
        raise DownloadError("download produced no file")
    return path
