"""The processing pipeline. Real stages swap in across tasks:
download (Task 4) -> transcribe (Task 5) -> research (Task 6, stub)."""

from app import store
from app.download import DownloadError, download_audio
from app.models import ReelStatus
from app.transcribe import transcribe_audio


def process_reel(reel_id: int) -> None:
    """Run the pipeline for one reel: download + transcribe are real; research still stubbed."""
    reel = store.get_reel(reel_id)
    if reel is None:
        return

    try:
        audio_path = download_audio(reel.url)  # audio saved to media/
    except DownloadError as exc:
        reel.status = ReelStatus.failed
        reel.error = f"download failed: {exc}"
        store.save_reel(reel)
        return

    try:
        reel.transcript = transcribe_audio(audio_path)
    except Exception as exc:  # decode/model errors -> mark failed, never crash the request
        reel.status = ReelStatus.failed
        reel.error = f"transcription failed: {exc}"
        store.save_reel(reel)
        return

    # research (Task 6) still stubbed
    reel.summary = "<stub summary — real research lands in Task 6>"
    reel.tools_links = '["<stub-tool-or-repo>"]'
    reel.tag = "idea"
    reel.take = "<stub do/skip take — personalized in Task 6>"
    reel.status = ReelStatus.done
    store.save_reel(reel)
