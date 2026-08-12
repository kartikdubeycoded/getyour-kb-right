"""analyze_item: a personalized depth + opportunity read for any radar item, NIM mocked."""

from app import research
from app.models import RadarItem


class FakeClient:
    def __init__(self):
        self.calls = []

    def complete(self, system, user):
        self.calls.append((system, user))
        return (
            '{"overview":"deep read","usage":"matters",'
            '"builds":["b1","b2"],"product_ideas":["p1"]}'
        )


def test_parses_and_carries_the_persons_focus():
    item = RadarItem(source="news", title="New tool X", url="https://x", summary="desc")
    c = FakeClient()
    data = research.analyze_item(item, {"focus": "AI agents", "goals": "ship a product"}, client=c)
    assert data["overview"] == "deep read"
    assert data["builds"] == ["b1", "b2"] and data["product_ideas"] == ["p1"]
    _system, user = c.calls[0]
    assert "AI agents" in user and "New tool X" in user  # personalized to focus + this item


def test_arxiv_framing_asks_for_the_research_gap():
    c = FakeClient()
    item = RadarItem(source="arxiv", title="Paper", url="u")
    research.analyze_item(item, {"focus": "ML"}, client=c)
    _system, user = c.calls[0]
    assert "GAP" in user  # arXiv items get the research-gap framing


class _FastFlagSpy:
    """Records whether the LLM was requested in fast (draft) mode; returns valid JSON."""

    def complete(self, system, user):
        return '{"overview":"o","usage":"u","builds":[],"product_ideas":[]}'


def _spy_make_llm(model=None, fast=False):
    _FastFlagSpy.last_fast = fast
    return _FastFlagSpy()


def test_draft_uses_the_fast_model(monkeypatch):
    monkeypatch.setattr(research, "make_llm", _spy_make_llm)
    research.analyze_item(RadarItem(source="news", title="t", url="u"), {})
    assert _FastFlagSpy.last_fast is True  # pass 1 = the provider's small/fast model


def test_critic_uses_the_main_model(monkeypatch):
    monkeypatch.setattr(research, "make_llm", _spy_make_llm)
    research.refine_analysis(RadarItem(source="news", title="t", url="u"), {}, {"overview": "d"})
    assert _FastFlagSpy.last_fast is False  # pass 2 = the strong model
