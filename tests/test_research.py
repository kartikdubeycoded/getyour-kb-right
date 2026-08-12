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


def test_llm_provider_env_picks_the_engine(monkeypatch):
    """The brain is swappable by one line in .env. Qwen is the strong-synthesis engine."""
    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    assert research._provider()["key_env"] == "DASHSCOPE_API_KEY"
    assert "dashscope" in research._provider()["base_url"]

    monkeypatch.setenv("LLM_PROVIDER", "groq")
    assert research._provider()["key_env"] == "GROQ_API_KEY"

    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    assert research._provider()["key_env"] == "DEEPSEEK_API_KEY"
    assert "deepseek" in research._provider()["base_url"]

    # An unknown name must FAIL LOUDLY, not fall back. Silently routing to the default engine
    # turns "LLM_PROVIDER names a provider nobody registered" into an unrelated rate-limit error
    # on a detail page several layers away — which is exactly how this bug hid for weeks.
    monkeypatch.setenv("LLM_PROVIDER", "nonsense")
    try:
        research._provider()
        raise AssertionError("expected RuntimeError for an unknown provider")
    except RuntimeError as exc:
        assert "nonsense" in str(exc)
        assert "deepseek" in str(exc)  # the error lists what IS valid

    # Unset (or blank) still defaults quietly to groq — that is a default, not a typo.
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert research._provider()["key_env"] == "GROQ_API_KEY"


def test_missing_key_names_the_variable_the_selected_engine_needs(monkeypatch):
    """Switching engines without its key should say WHICH key is missing, not fail cryptically."""
    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    try:
        research.LLMProviderClient()
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "DASHSCOPE_API_KEY" in str(exc)


PROFILE_WITH_PROJECTS = {
    "focus": "AI",
    "projects": [
        {"name": "Jay", "about": "local Ollama log-sniffer + voice hub"},
        {"name": "Portfolio", "about": "Three.js personal site"},
    ],
}


def test_prompt_names_the_projects_so_a_fit_can_be_suggested():
    """The model cannot suggest a project it was never told about — the whole feature is passing
    profile.projects into the prompt."""
    _system, user = research._build_prompt("t", PROFILE_WITH_PROJECTS)

    assert "Jay" in user and "local Ollama log-sniffer" in user
    assert "Portfolio" in user


def test_project_fit_is_parsed_onto_the_result():
    client = FakeClient(
        '{"summary":"s","tools_links":[],"tag":"tool","take":"do it",'
        '"project_fit":"Jay: swap this whisper build in for the voice hub"}'
    )
    result = research.research_reel("t", PROFILE_WITH_PROJECTS, client=client)
    assert result.project_fit.startswith("Jay:")


def test_a_fit_naming_a_project_he_does_not_have_is_dropped():
    """Models invent plausible project names. A suggestion pointing at a build he doesn't have is
    worse than no suggestion — he'd act on it."""
    client = FakeClient(
        '{"summary":"s","tools_links":[],"tag":"tool","take":"t",'
        '"project_fit":"Lexara: wire this into the legal RAG pipeline"}'
    )
    result = research.research_reel("t", PROFILE_WITH_PROJECTS, client=client)
    assert result.project_fit == ""


def test_no_fit_is_an_empty_string_not_a_stretch():
    client = FakeClient(
        '{"summary":"s","tools_links":[],"tag":"other","take":"skip","project_fit":""}'
    )
    assert research.research_reel("t", PROFILE_WITH_PROJECTS, client=client).project_fit == ""


def test_projects_block_survives_a_profile_with_no_projects():
    assert research._projects_block({}) == "(none declared)"
    assert research._projects_block({"projects": ["junk", {"no": "name"}]}) == "(none declared)"
