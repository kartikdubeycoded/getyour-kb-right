"""The Idea Space engine: turn a handful of radar items (news + repos + papers) into a few concrete
OPPORTUNITIES — things to build or papers to write — by finding the pattern or GAP across them.

This is the app's reason to exist: information becomes knowledge only when it's cross-referenced and
written into something the person can act on. One LLM pass reads a diverse slice of resources and
returns a short list of ideas, each grounded in the specific sources it connects.

The LLM engine comes from research.make_llm (Groq by default); tests inject a fake, no network."""

import json
import re

from app.research import LLMClient, _extract_json, make_llm

# Sources ranked by how well they seed a buildable/researchable idea: repos and papers are raw
# material for projects and hypotheses; gnews headlines are the weakest fuel. _diverse front-loads
# the pool in this order so synthesis reasons over repos + papers, not a stack of news headlines.
_SOURCE_PRIORITY = ["github", "arxiv", "hn", "reddit", "news", "gnews"]

_REF_TOKEN = re.compile(r"\[\s*\d+(?:\s*,\s*\d+)*\s*\]")  # "[5]", "[2, 8]" — resource-number leaks


def _strip_refs(text: str) -> str:
    """Remove leaked resource-number tokens like '[5]' from prose (sources show as chips anyway),
    then tidy the spacing the removal leaves — collapsing only horizontal runs so newlines (and the
    deep dive's section layout) survive."""
    t = _REF_TOKEN.sub("", text)
    t = re.sub(r"[ \t]{2,}", " ", t)        # collapse horizontal whitespace, keep line breaks
    t = re.sub(r" +([.,;:])", r"\1", t)     # tidy " ." / " ," left behind by the removal
    return t.strip()


def _diverse(items: list, want: int) -> list:
    """Pick up to `want` items spread ACROSS sources, richest sources first. A gap only shows up
    when a repo sits next to a paper sits next to a news item — so round-robin by source (newest
    first within each), visiting sources in _SOURCE_PRIORITY order so repos/papers lead and a
    gnews-heavy corpus can't crowd them out."""
    by_source: dict[str, list] = {}
    for it in items:
        by_source.setdefault(getattr(it, "source", "?"), []).append(it)
    order = [s for s in _SOURCE_PRIORITY if s in by_source]
    order += [s for s in by_source if s not in order]  # any unknown sources go last
    picked: list = []
    while len(picked) < want and any(by_source.values()):
        for src in order:
            bucket = by_source[src]
            if bucket:
                picked.append(bucket.pop(0))
                if len(picked) >= want:
                    break
    return picked


def _resource_lines(items: list) -> str:
    """The numbered resource list the model reasons over. The number lets the model tell us which
    resources an idea draws from (via the `sources` array) — but it's told to NAME them in prose."""
    lines = []
    for i, it in enumerate(items, 1):
        summary = (getattr(it, "summary", "") or "").strip().replace("\n", " ")
        lines.append(
            f"[{i}] ({getattr(it, 'source', '?')}) {it.title}\n"
            f"    {summary[:220] or '(no description)'}\n"
            f"    {getattr(it, 'url', '')}"
        )
    return "\n".join(lines)


def synthesize_ideas(
    items: list, profile: dict, client: LLMClient | None = None, want: int = 5, pool: int = 10
) -> list[dict]:
    """Cross-reference a diverse slice of the corpus into concrete ideas for THIS person. Returns a
    list of dicts: {title, kind, insight, plan, why_you, sources:[{title,source,url}]}. `kind` is
    'build' (a project/tool) or 'paper' (a research paper — including testing/extending a paper's
    hypothesis). Each idea's `sources` are the actual resources it was synthesized from, so the user
    can trace the reasoning. Returns [] if there's nothing to work with."""
    resources = _diverse(items, pool)
    if len(resources) < 2:  # a gap needs at least two things to sit between
        return []

    client = client or make_llm()
    system = (
        "You are a research-and-build strategist for ONE specific person. You are given several "
        "resources (news, GitHub repos, research papers) and their focus/goals. Find where "
        "two or more resources CONNECT or leave a GAP, then propose OPPORTUNITIES: things to "
        "build or papers to write. Do not summarize the resources. Reason across them. "
        "Return STRICT JSON only: an object {\"ideas\": [ ... ]}. Each idea has keys: "
        "title (short, concrete); "
        "kind (\"build\" for a project/tool, or \"paper\" for a research paper — including testing "
        "or extending a paper's stated hypothesis); "
        "sources (array of the resource NUMBERS it draws from, at least 2 when possible); "
        "insight (2-3 sentences naming the specific pattern or gap across those resources); "
        "plan (for build: the concrete thing to make and a realistic FIRST step; for paper: the "
        "hypothesis to test and how); "
        "why_you (1 sentence: why it fits this person's focus, goals, and reach). "
        "IMPORTANT: in insight/plan/why_you, refer to a resource by its NAME (e.g. 'the Piper "
        "paper', 'mindsdb') — NEVER by a number or bracket like [5]. Numbers are only for sources. "
        "Vary the resources across ideas; do not anchor every idea to the same one. "
        "Give 3-5 ideas, best first. Prefer ideas that combine 2+ resources over single-source. "
        "Return ONLY the JSON object."
    )
    user = (
        f"Person's focus: {profile.get('focus', '')}\n"
        f"Goals / situation: {profile.get('goals', '')}\n\n"
        f"RESOURCES:\n{_resource_lines(resources)}"
    )
    data = _extract_json(client.complete(system, user))
    raw_ideas = data.get("ideas") if isinstance(data, dict) else None
    if not isinstance(raw_ideas, list):
        return []

    out: list[dict] = []
    for raw in raw_ideas:
        if not isinstance(raw, dict) or not str(raw.get("title") or "").strip():
            continue
        srcs = []
        for n in raw.get("sources") or []:
            try:
                ref = resources[int(n) - 1]  # model cites 1-based resource numbers
            except (ValueError, TypeError, IndexError):
                continue
            srcs.append(
                {
                    "title": ref.title,
                    "source": getattr(ref, "source", "?"),
                    "url": getattr(ref, "url", ""),
                }
            )
        kind = "paper" if str(raw.get("kind", "")).lower().startswith("paper") else "build"
        out.append(
            {
                "title": _strip_refs(str(raw.get("title") or "")),
                "kind": kind,
                "insight": _strip_refs(str(raw.get("insight") or "")),
                "plan": _strip_refs(str(raw.get("plan") or "")),
                "why_you": _strip_refs(str(raw.get("why_you") or "")),
                "sources": srcs,
            }
        )
    return out[:want]


def deepen_idea(idea, profile: dict, client: LLMClient | None = None) -> str:
    """Expand an accepted idea into a concrete, actionable plan — the 'get into depth' step. For a
    build: what exactly to make, the stack, the pieces, the first week, how to validate, the
    portfolio/income angle, the risks. For a paper: the precise hypothesis, novelty vs the cited
    work, method and experiment design, what to measure, baselines, and a first concrete step.
    Returns readable prose (headed sections), grounded in the idea's own sources."""
    client = client or make_llm()
    srcs = json.loads(idea.sources or "[]")
    src_lines = "\n".join(f"- ({s.get('source')}) {s.get('title')} — {s.get('url')}" for s in srcs)
    if idea.kind == "paper":
        shape = (
            "Write a research plan with these headed sections: HYPOTHESIS (one precise, testable "
            "claim); NOVELTY (why the cited work hasn't answered it); METHOD (how to test it, "
            "concretely); EXPERIMENTS (datasets, baselines, what to measure); RISKS (what could "
            "sink it); FIRST STEP (one thing to do this week)."
        )
    else:
        shape = (
            "Write a build plan with these headed sections: WHAT TO BUILD (the concrete thing, in "
            "plain terms); STACK (tools/libraries, tuned to this person); PIECES (3-5 components "
            "and how they fit); FIRST WEEK (a day-by-day list of concrete steps); VALIDATE (how "
            "to know it works and is wanted); ANGLE (portfolio or income use); RISKS (what could "
            "sink it)."
        )
    system = (
        "You are a senior engineer-mentor turning an idea into an actionable plan for ONE specific "
        "person. Be concrete and specific — name real tools, real first steps, real numbers where "
        "you can. No fluff, no restating the idea. " + shape + " Use plain text with the section "
        "headings in CAPS on their own line. Refer to sources by name, never by bracket number."
    )
    user = (
        f"Person's focus: {profile.get('focus', '')}\n"
        f"Goals / situation: {profile.get('goals', '')}\n\n"
        f"IDEA: {idea.title}\n"
        f"The pattern/gap: {idea.insight}\n"
        f"Direction so far: {idea.plan}\n\n"
        f"Grounded in these resources:\n{src_lines or '(none)'}"
    )
    return _strip_refs(client.complete(system, user).strip())
