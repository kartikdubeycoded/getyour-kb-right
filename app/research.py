"""Research a reel's transcript with an LLM and produce a personalized do/skip take.

Default client is NVIDIA NIM (free, via the OpenAI-compatible endpoint), but anything implementing
LLMClient can be swapped in. Tests pass a fake client, so no key or network is needed."""

import json
import os
from dataclasses import dataclass, field
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
    key_takeaways: list[str] = field(default_factory=list)
    buildable: str = ""  # "yes" | "no"
    build_idea: str = ""  # if buildable: what to build
    monetization: str = ""  # if buildable: worst-case how to earn from it


def _build_prompt(
    transcript: str, profile: dict, caption: str | None = None, visual: str | None = None
) -> tuple[str, str]:
    system = (
        "You analyze a short Instagram reel for a specific person and return STRICT JSON only. "
        "You are given up to three signals about the reel: AUDIO (spoken words), CAPTION (the "
        "creator's text), and ON-SCREEN (text/scene read from the cover frame). Many reels are "
        "just music over on-screen text — in those, AUDIO is noise; trust CAPTION and ON-SCREEN. "
        "Weigh all available signals together. Keys: "
        "summary (about 60 words, concrete and plain — enough to know what the reel is about); "
        "key_takeaways (array of 2-4 short, concrete bullet points worth remembering, [] if none); "
        "tools_links (array of tool/repo/course names or URLs mentioned, [] if none); "
        "tag (one of: course, tool, idea, opportunity, other); "
        "take (1-2 sentences on whether THIS person should act on it. Weigh BOTH their focus AND "
        "their goals/situation — a high-value opportunity like a paid role, internship, or income "
        "lead can be worth acting on even if off-topic. Be practical, not rigid); "
        "buildable (\"yes\" or \"no\" — could THIS person build a useful tool/product/project from "
        "the idea or problem in this reel, given their focus and goals?); "
        "build_idea (if buildable yes: 1-2 sentences on the concrete thing to build; else \"\"); "
        "monetization (if buildable yes: 1 sentence on a realistic worst-case way to earn from "
        "it — freelance, a paid tool, a service; else \"\"). "
        "Return ONLY the JSON object — no prose, no code fences."
    )
    parts = [
        f"Person's focus: {profile.get('focus', '')}",
        f"Goals / situation: {profile.get('goals', '')}",
        f"Not interested in: {profile.get('not_interested', '')}",
        "",
        f"AUDIO (spoken):\n{transcript or '(none)'}",
        f"CAPTION:\n{caption or '(none)'}",
        f"ON-SCREEN (read from cover frame):\n{visual or '(none)'}",
    ]
    return system, "\n".join(parts)


def _extract_json(raw: str) -> dict:
    """Pull the JSON object out of the model output (it may wrap it in prose or code fences)."""
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in model output: {raw[:200]}")
    return json.loads(raw[start : end + 1])


def research_reel(
    transcript: str,
    profile: dict,
    client: LLMClient | None = None,
    caption: str | None = None,
    visual: str | None = None,
) -> ResearchResult:
    client = client or NvidiaNimClient()
    system, user = _build_prompt(transcript, profile, caption, visual)
    data = _extract_json(client.complete(system, user))
    return ResearchResult(
        summary=data.get("summary", ""),
        tools_links=data.get("tools_links") or [],
        tag=data.get("tag", "other"),
        take=data.get("take", ""),
        key_takeaways=data.get("key_takeaways") or [],
        buildable=(data.get("buildable") or "").lower(),
        build_idea=data.get("build_idea", ""),
        monetization=data.get("monetization", ""),
    )
