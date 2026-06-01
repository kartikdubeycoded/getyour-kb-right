from app import research
from app.research import ResearchResult


class FakeClient:
    def __init__(self, payload: str):
        self.payload = payload

    def complete(self, system: str, user: str) -> str:
        return self.payload


def test_research_parses_strict_json():
    client = FakeClient('{"summary":"s","tools_links":["x"],"tag":"tool","take":"do it"}')
    result = research.research_reel("transcript", {"focus": "AI"}, client=client)
    assert isinstance(result, ResearchResult)
    assert result.tag == "tool"
    assert result.tools_links == ["x"]
    assert result.take == "do it"


def test_research_extracts_json_wrapped_in_prose():
    client = FakeClient('Sure:\n{"summary":"s","tools_links":[],"tag":"idea","take":"skip"}\nDone')
    result = research.research_reel("t", {}, client=client)
    assert result.tag == "idea"
    assert result.take == "skip"


def test_research_raises_when_no_json():
    client = FakeClient("I could not produce JSON.")
    try:
        research.research_reel("t", {}, client=client)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
