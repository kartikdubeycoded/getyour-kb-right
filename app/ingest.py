"""The processing pipeline: download (Task 4) -> transcribe (Task 5) -> research (Task 6)."""

import json

from app import store
from app.download import DownloadError, download_media
from app.models import Reel, ReelStatus
from app.profile import load_profile
from app.research import research_reel
from app.transcribe import transcribe_audio
from app.vision import read_frame


def process_reel(reel_id: int) -> None:
    """Full pipeline for one reel: download -> hear (transcribe) + read (caption) + see (vision)
    -> research a fused take."""
    reel = store.get_reel(reel_id)
    if reel is None:
        return

    try:
        media = download_media(reel.url)
    except DownloadError as exc:
        return _fail(reel, f"download failed: {exc}")

    reel.caption = media.caption  # READ: the creator's caption (free, from yt-dlp)
    reel.visual = read_frame(media.thumbnail_url)  # SEE: on-screen text + scene (None on failure)

    try:
        reel.transcript = transcribe_audio(media.audio_path)  # HEAR: speech in the audio
    except Exception as exc:  # decode/model errors
        return _fail(reel, f"transcription failed: {exc}")

    try:
        result = research_reel(
            reel.transcript, load_profile(), caption=reel.caption, visual=reel.visual
        )
    except Exception as exc:  # missing key, network, or bad model output
        return _fail(reel, f"research failed: {exc}")

    reel.summary = result.summary
    reel.tools_links = json.dumps(result.tools_links)
    reel.key_takeaways = json.dumps(result.key_takeaways)
    reel.tag = result.tag
    reel.take = result.take
    reel.buildable = result.buildable
    reel.build_idea = result.build_idea
    reel.monetization = result.monetization
    reel.status = ReelStatus.done
    store.save_reel(reel)


def _fail(reel: Reel, reason: str) -> None:
    reel.status = ReelStatus.failed
    reel.error = reason
    store.save_reel(reel)
