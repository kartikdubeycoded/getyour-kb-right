"""'See' a reel: send its cover frame to a vision-language model and get back the on-screen text
plus a short description of what's shown. This is what fixes music/no-speech reels — the audio is
useless but the screen carries the real info.

Default client is an NVIDIA NIM vision model (free key, OpenAI-compatible), swappable behind
VisionClient. Vision is an ENHANCEMENT, never required: read_frame() returns None on any failure
(no URL, no key, network error, bad image) so the pipeline keeps working with audio + caption."""

import base64
import os
import urllib.request
from typing import Protocol

NIM_BASE_URL = os.getenv("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
NIM_VISION_MODEL = os.getenv("NIM_VISION_MODEL", "meta/llama-3.2-11b-vision-instruct")

_PROMPT = (
    "This is the cover frame of a short Instagram reel. First transcribe ALL text visible on "
    "screen, exactly. Then in one sentence say what is shown. Keep it under 80 words."
)


class VisionClient(Protocol):
    def describe(self, image_url: str) -> str: ...


_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124"


def _fetch_data_url(image_url: str, timeout: float = 10.0) -> str:
    """Download the public image and return it as a base64 data URL (NIM wants the image inline)."""
    req = urllib.request.Request(image_url, headers={"User-Agent": _UA})  # CDNs 403 the default UA
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (public CDN img)
        raw = resp.read()
        mime = resp.headers.get_content_type() or "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


class NvidiaNimVisionClient:
    """OpenAI-compatible NIM client for a vision model. Needs the free NVIDIA_API_KEY."""

    def __init__(self) -> None:
        from openai import OpenAI

        key = os.getenv("NVIDIA_API_KEY")
        if not key:
            raise RuntimeError("NVIDIA_API_KEY not set (get a free key at build.nvidia.com)")
        self._client = OpenAI(base_url=NIM_BASE_URL, api_key=key)
        self._model = NIM_VISION_MODEL

    def describe(self, image_url: str) -> str:
        data_url = _fetch_data_url(image_url)
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _PROMPT},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            temperature=0.2,
        )
        return resp.choices[0].message.content or ""


def read_frame(thumbnail_url: str | None, client: VisionClient | None = None) -> str | None:
    """What the vision model sees on the cover frame, or None if it can't (enhancement only)."""
    if not thumbnail_url:
        return None
    try:
        client = client or NvidiaNimVisionClient()
        text = client.describe(thumbnail_url).strip()
        return text or None
    except Exception:  # noqa: BLE001 — vision must never break the pipeline
        return None
