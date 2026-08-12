from app import synthesize
from app.models import RadarItem


class FakeClient:
    """Records the prompt and returns a canned payload — no key, no network."""

    def __init__(self, payload: str):
        self.payload = payload
        self.seen_user = None
        self.seen_system = None

    def complete(self, system: str, user: str) -> str:
        self.seen_user = user
        self.seen_system = system
        return self.payload


def _item(id_, source, title, summary="", url="http://x"):
    return RadarItem(id=id_, source=source, title=title, summary=summary, url=url)


def test_synthesize_parses_ideas_and_maps_source_numbers_to_real_resources():
    items = [
        _item(1, "github", "a repo", url="http://gh/1"),
        _item(2, "arxiv", "a paper", url="http://arx/2"),
        _item(3, "news", "some news", url="http://n/3"),
    ]
    payload = (
        '{"ideas": ['
        '{"title": "Bridge A and B", "kind": "build", "sources": [1, 2],'
        ' "insight": "gap", "plan": "do it", "why_you": "fits you"},'
        '{"title": "Extend the paper", "kind": "paper", "sources": [2],'
        ' "insight": "i2", "plan": "test H", "why_you": "w2"}'
        ']}'
    )
    ideas = synthesize.synthesize_ideas(items, {"focus": "AI"}, client=FakeClient(payload))

    assert len(ideas) == 2
    assert ideas[0]["title"] == "Bridge A and B" and ideas[0]["kind"] == "build"
    # the model's 1-based source numbers are resolved to the actual resources
    assert [s["url"] for s in ideas[0]["sources"]] == ["http://gh/1", "http://arx/2"]
    assert ideas[1]["kind"] == "paper"  # kind normalizes to build|paper


def test_synthesize_returns_empty_when_fewer_than_two_resources():
    # a gap needs two things to sit between; the client is never even called
    assert synthesize.synthesize_ideas([_item(1, "news", "x")], {}, client=FakeClient("{}")) == []


def test_synthesize_bad_payload_is_safe():
    items = [_item(1, "news", "a"), _item(2, "github", "b")]
    assert synthesize.synthesize_ideas(items, {}, client=FakeClient('{"nope": 1}')) == []


def test_diverse_spreads_across_sources_not_one_dominant():
    items = [_item(i, "gnews", f"g{i}") for i in range(10)]
    items += [_item(99, "github", "G"), _item(98, "arxiv", "A")]
    picked = synthesize._diverse(items, 8)
    srcs = {p.source for p in picked}
    assert "github" in srcs and "arxiv" in srcs  # rare sources aren't drowned by gnews


def test_diverse_leads_with_buildable_sources():
    items = [_item(i, "gnews", f"g{i}") for i in range(5)]
    items += [_item(99, "github", "G"), _item(98, "arxiv", "A")]
    picked = synthesize._diverse(items, 3)
    # repos/papers seed ideas better than headlines, so they lead the pool
    assert picked[0].source == "github" and picked[1].source == "arxiv"


def test_strip_refs_removes_bracket_numbers_but_keeps_newlines():
    assert synthesize._strip_refs("Piper [8] beats [2, 5] here.") == "Piper beats here."
    assert synthesize._strip_refs("A\nB\nC") == "A\nB\nC"  # section layout survives


def test_synthesize_strips_leaked_refs_from_prose():
    items = [_item(1, "arxiv", "paper", url="u1"), _item(2, "github", "repo", url="u2")]
    payload = (
        '{"ideas": [{"title": "T", "kind": "build", "sources": [1, 2],'
        ' "insight": "combine [1] and [2]", "plan": "use [2]", "why_you": "fits"}]}'
    )
    ideas = synthesize.synthesize_ideas(items, {}, client=FakeClient(payload))
    assert ideas[0]["insight"] == "combine and"  # bracket numbers gone from the shown text
    assert "[2]" not in ideas[0]["plan"]


def test_deepen_idea_uses_kind_specific_shape_and_cleans_output():
    class _Idea:
        kind = "paper"
        title = "Extend Piper"
        insight = "gap"
        plan = "test H"
        sources = '[{"source": "arxiv", "title": "Piper", "url": "u"}]'

    client = FakeClient("HYPOTHESIS\nPiper [3] scales.\nMETHOD\nrun it.")
    out = synthesize.deepen_idea(_Idea(), {"focus": "ML"}, client=client)
    assert "HYPOTHESIS" in client.seen_system and "EXPERIMENTS" in client.seen_system  # paper shape
    assert "[3]" not in out and "\n" in out  # refs stripped, section newlines kept
