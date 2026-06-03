"""Find a GitHub repo mentioned anywhere in a reel (caption / transcript / on-screen / links),
so the reel's detail page can link straight to that repo's breakdown. The GitHub tab thus becomes
a curated hub fed by BOTH the radar search and the reels themselves."""

import re

from app.models import Reel

# github.com/owner/repo — capture owner + repo, stop before extra path/query/punctuation.
_REPO_RE = re.compile(
    r"github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)/([A-Za-z0-9._-]+)",
    re.IGNORECASE,
)

# Not real repos — these are github.com paths that look like owner/repo but aren't.
_NOT_OWNERS = {"orgs", "topics", "features", "about", "pricing", "sponsors", "marketplace"}


def find_repo(reel: Reel) -> tuple[str, str] | None:
    """Return (full_name, canonical_url) for the first GitHub repo mentioned by the reel, or None.

    Scans every text field we collected. full_name is "owner/repo" — the same key the radar uses
    as a RadarItem.title, so an existing radar repo is reused instead of duplicated.
    """
    haystacks = [reel.caption, reel.visual, reel.transcript, reel.tools_links]
    for text in haystacks:
        if not text:
            continue
        for owner, repo in _REPO_RE.findall(text):
            if owner.lower() in _NOT_OWNERS:
                continue
            repo = repo.rstrip(".")  # trailing dot is sentence punctuation, not part of the name
            if repo.lower().endswith(".git"):
                repo = repo[:-4]
            full_name = f"{owner}/{repo}"
            return full_name, f"https://github.com/{full_name}"
    return None
