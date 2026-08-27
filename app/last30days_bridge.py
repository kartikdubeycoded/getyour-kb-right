"""Bridge to the vendored last30days-skill CLI (vendor/last30days-skill) — real crowd-engagement
signal (Reddit/HN/GitHub/arXiv/Polymarket, free tier, no keys) for a topic, so the critic pass can
ground its build/monetization verdict in what people are actually engaging with right now instead
of just the LLM's own guess. Best-effort: any failure (missing repo, timeout, no network) returns
None and the caller falls back to analysis without live signal — this must never break the pipeline
it's grounding."""

import subprocess
import sys
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "vendor"
    / "last30days-skill"
    / "skills"
    / "last30days"
    / "scripts"
    / "last30days.py"
)

_TIMEOUT_S = 100  # observed real runs ~70s; this is a background fetch, not a page-load blocker


def fetch_signal(topic: str, timeout: int = _TIMEOUT_S) -> str | None:
    """Real engagement-ranked evidence for `topic` from the last 30 days, as raw text for an LLM
    to read as grounding context. None if the vendored script is missing or the run fails/times out
    — deliberately swallowed here so a dead/slow research engine never blocks item analysis."""
    if not _SCRIPT.exists():
        return None
    try:
        result = subprocess.run(
            [sys.executable, str(_SCRIPT), topic, "--emit=compact"],
            capture_output=True,
            text=True,
            encoding="utf-8",  # the script emits UTF-8 (emoji etc.); Windows' default codepage
            errors="replace",  # (cp1252) can't decode that and crashes text-mode decoding
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0 or not result.stdout or not result.stdout.strip():
        return None
    return result.stdout
