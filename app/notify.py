"""Telegram push notifications for the heartbeat.

The radar refreshes itself every 6 hours and until now nobody was told: the only way to find out
what landed was to open the site. This module is the ambient tap on the shoulder — after a sync,
Katti gets one Telegram message summarising what is new, so he learns without opening anything.

Two hard safety rules, both deliberate and non-negotiable:

* **Config is read at CALL time, never import time.** ``is_configured`` and ``send_telegram`` call
  ``os.getenv`` inside the function, so tests can monkeypatch env vars and so a token added at
  runtime (or an env file loaded late) is picked up without a restart.
* **``send_telegram`` must NEVER raise.** A dead notifier must not be able to kill the heartbeat —
  that is the whole point of this safety requirement. Every failure path returns ``False`` and
  logs; the caller can decide to move on with the rest of the sync.

``build_digest`` is a PURE function: no network, no DB. It turns three already-ranked lists (ideas,
hackathons, radar items) into one HTML-safe message. Telegram only supports a tiny HTML subset, so
this module emits only ``<a>`` and ``<b>`` and HTML-escapes every value from the data before
interpolating it.
"""

import html
import json
import logging
import os
import re
import urllib.request

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

# Only used by _clamp's floor case, to strip markup from an over-long single line.
_TAG_RE = re.compile(r"<[^>]+>")

# Telegram's hard cap on message length. We cut a little short of it (plus the trailing "...") so
# the message can never spill over the limit — Telegram counts some character sequences differently
# and rejects anything at or over the cap.
MAX_MESSAGE_LEN = 4096


def is_configured() -> bool:
    """True only when BOTH TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set and non-empty."""
    return bool(os.getenv("TELEGRAM_BOT_TOKEN", "")) and bool(os.getenv("TELEGRAM_CHAT_ID", ""))


def _clamp(text: str) -> str:
    """Truncate safely below Telegram's 4096-char limit by dropping whole LINES from the end.

    Slicing at a raw character offset would eventually cut inside an ``<a href="...">`` tag, and
    Telegram rejects malformed HTML outright when ``parse_mode=HTML`` — a 400 that costs the whole
    message, not just the tail. Every line this module emits is a self-contained, balanced entry, so
    dropping lines can never leave a tag half-written. The character slice at the end is the floor
    case for a single line already longer than the cap; it strips tags rather than risk splitting
    one, because a plain-text tail still delivers.
    """
    if len(text) <= MAX_MESSAGE_LEN:
        return text
    lines = text.split("\n")
    while lines and len("\n".join([*lines, "..."])) > MAX_MESSAGE_LEN:
        lines.pop()
    if lines:
        return "\n".join([*lines, "..."])
    return html.escape(_TAG_RE.sub("", text))[: MAX_MESSAGE_LEN - 4] + "..."


def send_telegram(text: str) -> bool:
    """POST one message to Katti's Telegram chat. Never raises.

    Returns False immediately when unconfigured, and False (with a log line) on any network / JSON /
    API failure. Only a response whose ``ok`` field is truthy counts as a success.
    """
    if not is_configured():
        logging.warning("notify: TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set — nothing sent")
        return False

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    payload = {
        "chat_id": chat_id,
        "text": _clamp(text),
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    url = TELEGRAM_API.format(token=token)
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
    except Exception:  # noqa: BLE001 — the notifier must never take the heartbeat down with it
        logging.exception("notify: telegram send failed")
        return False

    ok = bool(body.get("ok"))
    if not ok:
        logging.warning("notify: telegram rejected the message: %s", body.get("description", ""))
    return ok


def _attr(obj, name: str, default: str = "") -> str:
    """Read an attribute defensively: a missing (or None) attribute yields ``default``, never
    raises."""
    value = getattr(obj, name, default)
    if value is None:
        return default
    return str(value)


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'s' if count != 1 else ''}"


def _link(title: str, url: str) -> str:
    """One escaped entry: ``<a href="URL">title</a>`` when a url is present, else the bare title."""
    escaped = html.escape(title)
    if url:
        return f'<a href="{html.escape(url, quote=True)}">{escaped}</a>'
    return escaped


def build_digest(ideas, opps, items) -> str:
    """Render an HTML-safe Telegram digest of what landed. Pure: no network, no DB.

    ``ideas`` / ``opps`` / ``items`` are assumed already ranked (ideas newest first, hackathons
    closing soonest, items hottest first) by the caller — this function only takes the top N of
    each. Accepts any object with ``.title`` / ``.url`` / ``.meta`` / ``.source`` attributes
    (RadarItem- or Idea-shaped); every read uses getattr with a default so a missing attribute
    cannot crash it. Returns "" when everything is empty, so the caller sends nothing.
    """
    ideas = ideas or []
    opps = opps or []
    items = items or []
    if not ideas and not opps and not items:
        return ""

    landed = []
    if ideas:
        landed.append(_plural(len(ideas), "idea"))
    if opps:
        landed.append(_plural(len(opps), "hackathon"))
    if items:
        landed.append(_plural(len(items), "item"))

    lines = ["<b>" + ", ".join(landed) + " landed</b>"]

    if ideas:
        lines.append("")
        lines.append("<b>New ideas</b>")
        lines.extend(_link(_attr(i, "title"), _attr(i, "url")) for i in ideas[:3])

    if opps:
        lines.append("")
        lines.append("<b>Hackathons closing soon</b>")
        for opp in opps[:3]:
            line = _link(_attr(opp, "title"), _attr(opp, "url"))
            meta = _attr(opp, "meta")
            if meta:
                line += " — " + html.escape(meta)
            lines.append(line)

    if items:
        lines.append("")
        lines.append("<b>Hot new items</b>")
        for item in items[:5]:
            line = _link(_attr(item, "title"), _attr(item, "url"))
            source = _attr(item, "source")
            if source:
                line += " (" + html.escape(source) + ")"
            lines.append(line)

    return "\n".join(lines)
