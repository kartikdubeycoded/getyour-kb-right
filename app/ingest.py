"""The processing pipeline. Real stages swap in across tasks:
download (Task 4, real) -> transcribe (Task 5, stub) -> research (Task 6, stub)."""

from app import store
from app.download import DownloadError, download_audio
from app.models import ReelStatus


def process_reel(reel_id: int) -> None:
    """Run the pipeline for one reel. Download is real; transcription/research still stubbed."""
    reel = store.get_reel(reel_id)
    if reel is None:
        return

    try:
        download_audio(reel.url)  # audio saved to media/; Task 5 will transcribe it
    except DownloadError as exc:
        reel.status = ReelStatus.failed
        reel.error = f"download failed: {exc}"
        store.save_reel(reel)
        return

    # transcription (Task 5) + research (Task 6) still stubbed
    reel.transcript = "<stub transcript — real transcription lands in Task 5>"
    reel.summary = "<stub summary — real research lands in Task 6>"
    reel.tools_links = '["<stub-tool-or-repo>"]'
    reel.tag = "idea"
    reel.take = "<stub do/skip take — personalized in Task 6>"
    reel.status = ReelStatus.done
    store.save_reel(reel)
