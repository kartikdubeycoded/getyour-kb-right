"""Local transcription via faster-whisper. Free, no API key. The model loads once (lazily, on first
real use), so importing this module stays cheap and tests can mock it without a download."""

import os
from functools import lru_cache
from pathlib import Path

MODEL_SIZE = os.getenv("WHISPER_MODEL", "base")  # base is a good CPU default for short reels


@lru_cache(maxsize=1)
def _model():
    """Load the model once. faster-whisper is imported here so this module imports without it."""
    from faster_whisper import WhisperModel

    return WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")


def transcribe_audio(audio_path: Path) -> str:
    """Transcribe an audio file to a single text string."""
    segments, _info = _model().transcribe(str(audio_path))
    return " ".join(seg.text.strip() for seg in segments).strip()
