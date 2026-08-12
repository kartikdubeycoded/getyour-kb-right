"""Tech-radar source #4: RSS news. Pulls recent items from tech-news sites and lab/vendor blogs via
their open RSS feeds (no key, no auth, no captcha — RSS exists to be read by machines, so it's
ToS-safe, unlike scraping). Returns RadarItems in the same shape as the other sources, so they
share the table, store, and feed UI. Items are scored by how well they match the user's focus
topics, so news that matters to this person floats to the top."""

import re

import feedparser

from app import freshness
from app.github_radar import topics_from_profile  # reuse the "topics from focus line" logic
from app.models import RadarItem

_UA = "get-your-knowledge-right"

# (display name, feed url). The ONLY thing to edit to add/remove a source — code never changes.
# Tech news + straight-from-the-lab/vendor blogs (zero-latency: the same post SF reads at 9am).
#
# Probing log, 2026-08-12: these have NO working RSS (404/401/500 on every variant tried), so a
# future session must NOT waste time re-probing them — they need a different mechanism, not a feed
# URL: Anthropic, Meta AI, Mistral, deeplearning.ai's The Batch, Kaggle competitions, Hugging Face
# Papers.
DEFAULT_FEEDS: list[tuple[str, str]] = [
    # general tech press
    ("The Verge", "https://www.theverge.com/rss/index.xml"),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
    ("TechCrunch", "https://techcrunch.com/feed/"),
    # straight from the labs — the same post SF reads at 9am
    ("OpenAI", "https://openai.com/news/rss.xml"),
    ("NVIDIA", "https://blogs.nvidia.com/feed/"),
    ("Microsoft", "https://blogs.microsoft.com/feed/"),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml"),
    ("Google Research", "https://research.google/blog/rss/"),
    ("Hugging Face", "https://huggingface.co/blog/feed.xml"),
    # WHO IS FUNDING WHAT, and what they're asking builders to make. This is the layer that was
    # missing: the radar knew what EXISTS but not what the people writing cheques want built.
    ("Y Combinator", "https://www.ycombinator.com/blog/rss"),
    ("Sequoia", "https://www.sequoiacap.com/feed/"),
    # a16z publishes on Substack, NOT on a16z.com — a16z.com/feed/ and /podcasts/feed/ both 404.
    # This is the one that resolves (it 301s to www.a16z.news/feed). Don't "fix" it back to the
    # main domain; that path was probed live twice and has no feed.
    ("a16z", "https://a16z.substack.com/feed"),
    ("Product Hunt", "https://www.producthunt.com/feed"),
    # practitioners who surface new tools days before the press does
    ("Latent Space", "https://www.latent.space/feed"),
    ("Simon Willison", "https://simonwillison.net/atom/everything/"),
    ("Lobsters", "https://lobste.rs/rss"),
    # curated newsletters — a human already filtered the firehose
    ("Import AI", "https://importai.substack.com/feed"),
    ("TLDR", "https://tldr.tech/api/rss/tech"),
    # engineering + web-craft (the Web Design lane is thin)
    ("Cloudflare", "https://blog.cloudflare.com/rss/"),
    ("Smashing Magazine", "https://www.smashingmagazine.com/feed/"),
]

_TAG_RE = re.compile(r"<[^>]+>")


def feeds_from_profile(profile: dict) -> list[tuple[str, str]]:
    """Feeds to pull: profile.news_feeds if set (list of {name,url} dicts or bare url strings),
    else the built-in DEFAULT_FEEDS."""
    custom = profile.get("news_feeds")
    if isinstance(custom, list) and custom:
        out: list[tuple[str, str]] = []
        for f in custom:
            if isinstance(f, dict) and f.get("url"):
                out.append((str(f.get("name") or f["url"]), str(f["url"])))
            elif isinstance(f, str) and f.strip():
                out.append((f.strip(), f.strip()))
        if out:
            return out
    return DEFAULT_FEEDS


def _clean(text: str, limit: int = 300) -> str:
    """Strip HTML tags and collapse whitespace from a feed summary, truncated for the card."""
    text = _TAG_RE.sub("", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _score(text: str, topics: list[str]) -> int:
    """How many focus topics this item mentions — on-target news ranks above general headlines."""
    low = text.lower()
    return sum(1 for t in topics if t.lower() in low)


def fetch_news(profile: dict, per_feed: int = 6) -> list[RadarItem]:
    """Recent items across the configured feeds, de-duplicated, as RadarItems (source='news').
    Scored by focus-topic match so the news that matters to this person rises to the top."""
    topics = topics_from_profile(profile)
    collected: list[tuple[float, RadarItem]] = []
    seen: set[str] = set()
    for name, url in feeds_from_profile(profile):
        try:
            parsed = feedparser.parse(url, agent=_UA)
        except Exception:  # noqa: BLE001 — one bad feed shouldn't sink the whole refresh
            continue
        for entry in parsed.entries[:per_feed]:
            link = entry.get("link")
            title = entry.get("title")
            if not link or not title or link in seen:
                continue
            seen.add(link)
            summary = _clean(entry.get("summary", ""))
            published = freshness.from_struct_time(
                entry.get("published_parsed") or entry.get("updated_parsed")
            )
            collected.append(
                (
                    published.timestamp() if published else 0.0,
                    RadarItem(
                        source="news",
                        title=title,
                        url=link,
                        summary=summary or None,
                        meta=f"📰 {name}",
                        score=_score(f"{title} {summary}", topics),
                        published_at=published,
                    ),
                )
            )
    # Insert oldest-first so that, within an equal topic-score, the newest item gets the highest id
    # and therefore sorts first in store.list_radar (which orders by score desc, then id desc).
    collected.sort(key=lambda pair: pair[0])
    return [item for _ts, item in collected]
