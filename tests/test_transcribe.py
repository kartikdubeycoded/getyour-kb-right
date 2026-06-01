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

    audio = tmp_path / "clip.m4a"
    audio.write_bytes(b"x")
    assert transcribe.transcribe_audio(audio) == "hello world"
