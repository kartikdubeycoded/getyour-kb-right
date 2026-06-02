"""Download a public reel with yt-dlp. Returns a Media bundle (audio path + caption + thumbnail
URL); raises DownloadError on anything yt-dlp can't fetch (private, removed, unsupported, or
network error). Audio lands in media/ (gitignored); faster-whisper decodes it directly — no system
ffmpeg needed. The caption + thumbnail let the pipeline 'see' the reel, not just hear it."""

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

MEDIA_DIR = Path(os.getenv("MEDIA_DIR", "media"))


class DownloadError(Exception):
    """yt-dlp could not fetch the URL (private, removed, unsupported, or network issue)."""


@dataclass
class Media:
    """Everything one yt-dlp fetch gives us about a reel."""

    audio_path: Path
    caption: str | None = None  # the creator's caption (often where the real info lives)
    thumbnail_url: str | None = None  # cover frame; fed to the vision model later


def download_media(url: str, media_dir: Path = MEDIA_DIR) -> Media:
    """Fetch a reel's audio + metadata. Returns a Media bundle."""
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
    return Media(
        audio_path=path,
        caption=(info.get("description") or None),
        thumbnail_url=(info.get("thumbnail") or None),
    )
