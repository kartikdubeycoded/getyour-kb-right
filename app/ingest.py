"""The processing pipeline. v1 skeleton fills stub fields so the whole path works end-to-end;
Tasks 4-6 swap in the real stages: yt-dlp download -> faster-whisper -> NVIDIA NIM research."""

from app import store
from app.models import ReelStatus


def process_reel(reel_id: int) -> None:
    """Run the pipeline for one reel. STUB for now — real stages land in Tasks 4-6."""
    reel = store.get_reel(reel_id)
    if reel is None:
        return
    reel.transcript = "<stub transcript — real transcription lands in Task 5>"
    reel.summary = "<stub summary — real research lands in Task 6>"
    reel.tools_links = '["<stub-tool-or-repo>"]'
    reel.tag = "idea"
    reel.take = "<stub do/skip take — personalized in Task 6>"
    reel.status = ReelStatus.done
    store.save_reel(reel)
