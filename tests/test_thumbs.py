from contextlib import contextmanager

from app import thumbs


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


@contextmanager
def _fake_urlopen_ctx(data):
    yield _FakeResp(data)


def test_save_thumbnail_writes_file_and_returns_local_path(monkeypatch, tmp_path):
    monkeypatch.setattr(thumbs, "THUMB_DIR", tmp_path)
    monkeypatch.setattr(
        thumbs.urllib.request, "urlopen", lambda *a, **k: _fake_urlopen_ctx(b"JPEGBYTES")
    )
    path = thumbs.save_thumbnail("https://cdn/x.jpg", 7)
    assert path == "/thumb/7"
    assert (tmp_path / "7.jpg").read_bytes() == b"JPEGBYTES"


def test_save_thumbnail_none_url_returns_none():
    assert thumbs.save_thumbnail(None, 1) is None


def test_save_thumbnail_swallows_network_error(monkeypatch, tmp_path):
    monkeypatch.setattr(thumbs, "THUMB_DIR", tmp_path)

    def boom(*a, **k):
        raise OSError("CDN refused")

    monkeypatch.setattr(thumbs.urllib.request, "urlopen", boom)
    assert thumbs.save_thumbnail("https://cdn/x.jpg", 2) is None  # never breaks the pipeline
