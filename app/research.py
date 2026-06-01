"""Research a reel's transcript with an LLM and produce a personalized do/skip take.

Default client is NVIDIA NIM (free, via the OpenAI-compatible endpoint), but anything implementing
LLMClient can be swapped in. Tests pass a fake client, so no key or network is needed."""

import json
import os
from dataclasses import dataclass
from typing import Protocol

NIM_BASE_URL = os.getenv("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
NIM_MODEL = os.getenv("NIM_MODEL", "meta/llama-3.3-70b-instruct")


class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class NvidiaNimClient:
    """OpenAI-compatible client for NVIDIA NIM. Needs a free NVIDIA_API_KEY (build.nvidia.com)."""

    def __init__(self) -> None:
        from openai import OpenAI

        key = os.getenv("NVIDIA_API_KEY")
        if not key:
            raise RuntimeError("NVIDIA_API_KEY not set (get a free key at build.nvidia.com)")
        self._client = OpenAI(base_url=NIM_BASE_URL, api_key=key)
        self._model = NIM_MODEL

    def complete(self, system: str, user: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
        )
        return resp.choices[0].message.content or ""


@dataclass
class ResearchResult:
    summary: str
    tools_links: list[str]
    tag: str  # course | tool | idea | other
    take: str


def _build_prompt(transcript: str, profile: dict) -> tuple[str, str]:
    system = (
        "You analyze the transcript of a short Instagram reel for a specific person and return "
        "STRICT JSON only. Keys: "
        "summary (about 60 words, concrete and plain — enough to know what the reel is about); "
        "tools_links (array of tool/repo/course names or URLs mentioned, [] if none); "
        "tag (one of: course, tool, idea, opportunity, other); "
        "take (1-2 sentences on whether THIS person should act on it. Weigh BOTH their focus AND "
        "their goals/situation — a high-value opportunity like a paid role, internship, or income "
        "lead can be worth acting on even if off-topic. Be practical, not rigid). "
        "Return ONLY the JSON object — no prose, no code fences."
    )
    user = (
        f"Person's focus: {profile.get('focus', '')}\n"
        f"Goals / situation: {profile.get('goals', '')}\n"
        f"Not interested in: {profile.get('not_interested', '')}\n\n"
        f"Transcript:\n{transcript}"
    )
    return system, user


def _extract_json(raw: str) -> dict:
    """Pull the JSON object out of the model output (it may wrap it in prose or code fences)."""
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in model output: {raw[:200]}")
    return json.loads(raw[start : end + 1])


def research_reel(
    transcript: str, profile: dict, client: LLMClient | None = None
) -> ResearchResult:
    client = client or NvidiaNimClient()
    system, user = _build_prompt(transcript, profile)
    data = _extract_json(client.complete(system, user))
    return ResearchResult(
        summary=data.get("summary", ""),
        tools_links=data.get("tools_links") or [],
        tag=data.get("tag", "other"),
        take=data.get("take", ""),
    )
