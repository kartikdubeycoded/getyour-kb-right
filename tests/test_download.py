import types
from pathlib import Path

import pytest

from app import download


class FakeYDL:
    """Stand-in for yt_dlp.YoutubeDL — no network. Writes a dummy file the code expects."""

    def __init__(self, opts):
        self.opts = opts
        self._path = ""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        if "bad" in url:
            raise RuntimeError("Unsupported URL / private")
        self._path = self.opts["outtmpl"].replace("%(ext)s", "m4a")
        Path(self._path).write_bytes(b"fake-audio")
        return {"ext": "m4a"}

    def prepare_filename(self, info):
        return self._path


def test_download_audio_returns_existing_path(monkeypatch, tmp_path):
    monkeypatch.setattr(download, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYDL))
    path = download.download_audio("https://insta/reel/ok", media_dir=tmp_path)
    assert path.exists()
    assert path.read_bytes() == b"fake-audio"


def test_download_audio_raises_downloaderror_on_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(download, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYDL))
    with pytest.raises(download.DownloadError):
        download.download_audio("https://insta/reel/bad", media_dir=tmp_path)
