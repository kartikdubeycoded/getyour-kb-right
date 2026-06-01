"""The processing pipeline: download (Task 4) -> transcribe (Task 5) -> research (Task 6)."""

import json

from app import store
from app.download import DownloadError, download_audio
from app.models import Reel, ReelStatus
from app.profile import load_profile
from app.research import research_reel
from app.transcribe import transcribe_audio


def process_reel(reel_id: int) -> None:
    """Run the full pipeline for one reel: download -> transcribe -> research."""
    reel = store.get_reel(reel_id)
    if reel is None:
        return

    try:
        audio_path = download_audio(reel.url)
    except DownloadError as exc:
        return _fail(reel, f"download failed: {exc}")

    try:
        reel.transcript = transcribe_audio(audio_path)
    except Exception as exc:  # decode/model errors
        return _fail(reel, f"transcription failed: {exc}")

    try:
        result = research_reel(reel.transcript, load_profile())
    except Exception as exc:  # missing key, network, or bad model output
        return _fail(reel, f"research failed: {exc}")

    reel.summary = result.summary
    reel.tools_links = json.dumps(result.tools_links)
    reel.tag = result.tag
    reel.take = result.take
    reel.status = ReelStatus.done
    store.save_reel(reel)


def _fail(reel: Reel, reason: str) -> None:
    reel.status = ReelStatus.failed
    reel.error = reason
    store.save_reel(reel)
