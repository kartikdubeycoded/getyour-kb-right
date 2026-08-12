"""Card visuals for radar items. A magazine layout needs an image on every card, but only some
sources give us one for free. This derives a thumbnail URL cheaply — no API call, no scraping:
GitHub items use the owner's avatar (github.com/<owner>.png). Everything else returns None, and
the template paints a designed per-source gradient tile instead of a broken/empty image."""

from urllib.parse import urlparse


def _github_owner(url: str) -> str | None:
    """The <owner> out of a https://github.com/<owner>/<repo> URL, or None if there isn't one."""
    path = urlparse(url or "").path.strip("/")
    owner = path.split("/")[0] if path else ""
    return owner or None


def card_image(item) -> str | None:
    """A thumbnail URL for a radar card, or None when we have no free image for that source."""
    source = getattr(item, "source", "") or ""
    url = getattr(item, "url", "") or ""
    if source in ("github", "trending"):  # both are repos — use the owner's avatar
        owner = _github_owner(url)
        if owner:
            return f"https://github.com/{owner}.png?size=160"
    return None
