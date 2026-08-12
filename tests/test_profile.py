from app import profile


def test_profile_yaml_env_overrides_the_file(monkeypatch):
    monkeypatch.setenv("PROFILE_YAML", "focus: shipping\nprojects: [{name: Jay, topics: [Ollama]}]")
    p = profile.load_profile()
    assert p["focus"] == "shipping"  # deployed profile arrives via env, not a file in the image
    assert p["projects"][0]["name"] == "Jay"


def test_profile_falls_back_to_file_when_env_unset(monkeypatch):
    monkeypatch.delenv("PROFILE_YAML", raising=False)
    p = profile.load_profile()
    assert isinstance(p, dict)  # loads profile.yaml / profile.example.yaml without crashing
