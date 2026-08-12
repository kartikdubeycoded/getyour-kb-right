"""Transcription. Default is local faster-whisper (free, no key). Set TRANSCRIBER=groq to use Groq's
hosted Whisper instead — fast, and it keeps a deployed container light (no model download, low RAM),
so the app runs on a cheap always-on host. Groq reuses GROQ_API_KEY."""

import os
from functools import lru_cache
from pathlib import Path

MODEL_SIZE = os.getenv("WHISPER_MODEL", "base")  # base is a good CPU default for short reels
GROQ_WHISPER_MODEL = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")


@lru_cache(maxsize=1)
def _model():
    """Load the local model once (faster-whisper imported here so the module imports cheaply)."""
    from faster_whisper import WhisperModel

    return WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")


def _transcribe_local(audio_path: Path) -> str:
    segments, _info = _model().transcribe(str(audio_path))
    return " ".join(seg.text.strip() for seg in segments).strip()


def _transcribe_groq(audio_path: Path) -> str:
    """Hosted Whisper on Groq — no local model, so the deploy stays small. Uses GROQ_API_KEY."""
    from openai import OpenAI

    client = OpenAI(
        base_url=os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
        api_key=os.environ["GROQ_API_KEY"],
    )
    with open(audio_path, "rb") as fh:
        resp = client.audio.transcriptions.create(model=GROQ_WHISPER_MODEL, file=fh)
    return (resp.text or "").strip()


def transcribe_audio(audio_path: Path) -> str:
    """Transcribe an audio file to text — via Groq's hosted Whisper when TRANSCRIBER=groq, else the
    local faster-whisper model."""
    if os.getenv("TRANSCRIBER", "local").strip().lower() == "groq":
        return _transcribe_groq(audio_path)
    return _transcribe_local(audio_path)
