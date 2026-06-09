"""card_image() derives a free thumbnail for a radar card (GitHub avatar) or None as the signal
to paint a gradient fallback tile."""

from app.cards import card_image
from app.models import RadarItem


def test_github_item_uses_owner_avatar():
    item = RadarItem(source="github", title="FastAPI", url="https://github.com/tiangolo/fastapi")
    assert card_image(item) == "https://github.com/tiangolo.png?size=160"


def test_github_handles_trailing_slash():
    item = RadarItem(source="github", title="x", url="https://github.com/owner/repo/")
    assert card_image(item) == "https://github.com/owner.png?size=160"


def test_github_without_owner_returns_none():
    assert card_image(RadarItem(source="github", title="x", url="https://github.com")) is None


def test_non_github_sources_have_no_image():
    for src in ("news", "hn", "arxiv", "gnews", "reddit"):
        item = RadarItem(source=src, title="x", url="https://example.com/article")
        assert card_image(item) is None
