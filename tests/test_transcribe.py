import types

from app import transcribe


class _Seg:
    def __init__(self, text):
        self.text = text


def test_transcribe_joins_segment_text(monkeypatch, tmp_path):
    fake_model = types.SimpleNamespace(
        transcribe=lambda _path: ([_Seg(" hello "), _Seg("world ")], None)
    )
    monkeypatch.setattr(transcribe, "_model", lambda: fake_model)
    monkeypatch.delenv("TRANSCRIBER", raising=False)  # default = local

    audio = tmp_path / "clip.m4a"
    audio.write_bytes(b"x")
    assert transcribe.transcribe_audio(audio) == "hello world"


def test_transcriber_env_routes_to_groq(monkeypatch, tmp_path):
    monkeypatch.setenv("TRANSCRIBER", "groq")
    monkeypatch.setattr(transcribe, "_transcribe_groq", lambda _p: "from groq")
    audio = tmp_path / "clip.m4a"
    audio.write_bytes(b"x")
    assert transcribe.transcribe_audio(audio) == "from groq"  # deploy path, no local model loaded
