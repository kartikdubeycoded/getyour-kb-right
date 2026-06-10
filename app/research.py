"""Research a reel's transcript with an LLM and produce a personalized do/skip take.

Default client is NVIDIA NIM (free, via the OpenAI-compatible endpoint), but anything implementing
LLMClient can be swapped in. Tests pass a fake client, so no key or network is needed."""

import json
import os
from dataclasses import dataclass, field
from typing import Protocol

NIM_BASE_URL = os.getenv("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
NIM_MODEL = os.getenv("NIM_MODEL", "meta/llama-3.3-70b-instruct")
# A small, fast model for the cheap first pass (the draft); the critic uses the strong NIM_MODEL.
NIM_DRAFT_MODEL = os.getenv("NIM_DRAFT_MODEL", "meta/llama-3.1-8b-instruct")


class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class NvidiaNimClient:
    """OpenAI-compatible client for NVIDIA NIM. Needs a free NVIDIA_API_KEY (build.nvidia.com)."""

    def __init__(self, model: str | None = None) -> None:
        from openai import OpenAI

        key = os.getenv("NVIDIA_API_KEY")
        if not key:
            raise RuntimeError("NVIDIA_API_KEY not set (get a free key at build.nvidia.com)")
        self._client = OpenAI(base_url=NIM_BASE_URL, api_key=key)
        self._model = model or NIM_MODEL

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


_ANGLE_BY_SOURCE = {
    "arxiv": (
        "This is a RESEARCH PAPER. In `builds`, name the concrete research GAP it leaves open and "
        "whether a new paper or extension is realistically within this person's reach."
    ),
    "github": "This is a tool/repo. In `builds`, name projects this person could ship USING it.",
    "hn": "A discussion/launch. In `builds`, name what this person could build off the idea.",
    "news": "News. In `builds`, name any new tool/opening it creates that this person could use.",
    "reddit": "A discussion. In `builds`, name what this person could build off it.",
}
_ANGLE_BY_SOURCE["gnews"] = _ANGLE_BY_SOURCE["news"]


def analyze_item(item, profile: dict, client: LLMClient | None = None) -> dict:
    """Depth + a PERSONAL opportunity read for any radar item (not GitHub — that has its own
    README-based path). Returns {overview, usage, builds[], product_ideas[]} so it caches into the
    same RadarItem fields. `overview` is the 60-100 word depth; `usage` is why it matters to THIS
    person; `builds`/`product_ideas` are what they could build/monetize."""
    client = client or NvidiaNimClient(model=NIM_DRAFT_MODEL)  # cheap fast draft
    angle = _ANGLE_BY_SOURCE.get(getattr(item, "source", ""), _ANGLE_BY_SOURCE["news"])
    system = (
        "You analyze a tech item FOR one specific builder and return STRICT JSON only. Keys: "
        "overview (60-100 words, plain language: what it actually is, in depth); "
        "usage (1-2 sentences: why it matters to THIS person given their focus and goals); "
        "builds (array of 2-4 concrete things THIS person could build or do with it); "
        "product_ideas (array of 1-3 monetizable angles — freelance offer, paid tool, service). "
        "Be concrete and specific, tied to their focus. Return ONLY the JSON object."
    )
    user = (
        f"Source: {getattr(item, 'source', '')}\n"
        f"Item: {item.title}\n"
        f"Description: {item.summary or '(none)'}\n"
        f"Link: {item.url}\n"
        f"Person's focus: {profile.get('focus', '')}\n"
        f"Goals / situation: {profile.get('goals', '')}\n\n"
        f"{angle}"
    )
    return _extract_json(client.complete(system, user))


def refine_analysis(item, profile: dict, draft: dict, client: LLMClient | None = None) -> dict:
    """Second pass: a critic reviews the analyst's draft and rewrites it DEEPER. Same keys back
    (overview/usage/builds/product_ideas). This is the 'second agent judging the first' — the draft
    tends to be generic; the critic forces specifics, mechanisms, and a concrete first step."""
    client = client or NvidiaNimClient()
    system = (
        "You are a senior reviewer improving a shallow draft analysis. Rewrite it to be DEEPER and "
        "specific to this person. Rules: overview must teach the actual substance (name the "
        "mechanism/approach/specifics, not vague claims), 90-130 words; usage states the concrete "
        "reason it matters to THEM; each item in builds is a specific project WITH a first step; "
        "product_ideas are realistic for a solo builder with a path to first rupee. Keep the same "
        "JSON keys (overview, usage, builds, product_ideas). Return ONLY the JSON object."
    )
    user = (
        f"Item: {item.title}\nSource: {getattr(item, 'source', '')}\n"
        f"Description: {item.summary or '(none)'}\n"
        f"Person's focus: {profile.get('focus', '')}\nGoals: {profile.get('goals', '')}\n\n"
        f"DRAFT to improve:\n{json.dumps(draft)}"
    )
    return _extract_json(client.complete(system, user))


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
