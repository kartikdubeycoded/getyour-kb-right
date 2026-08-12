"""The Telegram notifier: an ambient tap on the shoulder after each heartbeat.

These cover the parts that decide whether the notifier is trustworthy rather than just present —
that it reads config at call time, that a dead notifier can never kill the heartbeat (every failure
returns False and nothing raises), that the right URL/body go out, that long messages are clamped
under Telegram's cap, and that the digest escapes every value and caps each section. No test touches
the network: ``urllib.request.urlopen`` is monkeypatched.
"""

import json
import urllib.error

from app import notify
from app.models import Idea, RadarItem


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# --- configuration ---


def test_is_configured_requires_both_vars_non_empty(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert notify.is_configured() is False  # neither

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    assert notify.is_configured() is False  # token only

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    assert notify.is_configured() is False  # chat only, token empty

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    assert notify.is_configured() is True  # both non-empty


def test_send_telegram_unconfigured_returns_false_and_never_calls_network(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    def boom(req, timeout=None):  # pragma: no cover - must never be reached
        raise AssertionError("urlopen must not be called when unconfigured")

    monkeypatch.setattr(notify.urllib.request, "urlopen", boom)

    assert notify.send_telegram("hello") is False  # no raise


def test_send_telegram_swallows_an_http_error(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")

    def boom(req, timeout=None):
        raise urllib.error.URLError("network down")

    monkeypatch.setattr(notify.urllib.request, "urlopen", boom)

    assert notify.send_telegram("hello") is False  # no raise


def test_send_telegram_posts_to_token_url_with_chat_id_and_html_body(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat456")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["data"] = req.data
        captured["headers"] = req.headers
        captured["timeout"] = timeout
        return _FakeResponse(b'{"ok": true}')

    monkeypatch.setattr(notify.urllib.request, "urlopen", fake_urlopen)

    ok = notify.send_telegram("a <b>new</b> thing")

    assert ok is True
    assert captured["url"] == "https://api.telegram.org/bottok123/sendMessage"
    assert "tok123" in captured["url"]
    assert captured["timeout"] == 15
    body = json.loads(captured["data"])
    assert body["chat_id"] == "chat456"
    assert body["text"] == "a <b>new</b> thing"
    assert body["parse_mode"] == "HTML"
    assert body["disable_web_page_preview"] is False


def test_long_message_is_truncated_before_sending(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["data"] = req.data
        return _FakeResponse(b'{"ok": true}')

    monkeypatch.setattr(notify.urllib.request, "urlopen", fake_urlopen)

    long_text = "x" * 5000
    assert notify.send_telegram(long_text) is True

    sent = json.loads(captured["data"])["text"]
    assert len(sent) <= notify.MAX_MESSAGE_LEN
    assert len(sent) < len(long_text)


# --- the digest ---


def test_build_digest_of_three_empty_lists_is_empty():
    assert notify.build_digest([], [], []) == ""


def test_build_digest_html_escapes_titles_and_meta():
    idea = Idea(title="Repo <script> & fish")
    opp = RadarItem(source="opps", title="Hack", url="https://h", meta="<b>bold</b> & deadline")

    digest = notify.build_digest([idea], [opp], [])

    assert "<script>" not in digest  # raw tag must not survive into the message
    assert "&lt;script&gt;" in digest
    assert "&amp;" in digest  # ampersand escaped in the title
    assert "<b>bold</b>" not in digest  # raw tag in meta must not survive either
    assert "&lt;b&gt;bold&lt;/b&gt; &amp; deadline" in digest


def test_build_digest_caps_each_section_at_3_3_5(monkeypatch):
    ideas = [Idea(title=f"idea {i}") for i in range(5)]
    opps = [
        RadarItem(source="opps", title=f"hack {i}", url=f"https://h/{i}", meta="closing soon")
        for i in range(5)
    ]
    items = [
        RadarItem(source="github", title=f"repo {i}", url=f"https://r/{i}") for i in range(8)
    ]

    digest = notify.build_digest(ideas, opps, items)

    # the first 3 / 3 / 5 are present...
    assert "idea 0" in digest and "idea 2" in digest
    assert "hack 0" in digest and "hack 2" in digest
    assert "repo 0" in digest and "repo 4" in digest
    # ...and the beyond-cap entries are dropped
    assert "idea 3" not in digest
    assert "hack 3" not in digest
    assert "repo 5" not in digest


def test_idea_without_url_or_meta_renders_as_bare_escaped_title():
    """Idea has no .url/.meta/.source — getattr defaults must let it through unscathed."""
    idea = Idea(title="Plain idea")

    digest = notify.build_digest([idea], [], [])

    assert "Plain idea" in digest
    assert "<a href" not in digest  # nothing to link


# --- clamping must never produce HTML Telegram will reject ---


def test_clamp_drops_whole_lines_instead_of_splitting_a_tag():
    """A raw character slice eventually cuts inside <a href="...">, and Telegram rejects malformed
    HTML outright when parse_mode=HTML — a 400 that costs the WHOLE message, not just the tail.
    Dropping whole lines can never leave a tag half-written."""
    long_line = '<a href="https://example.com/{n}">' + "x" * 200 + "</a>"
    text = "\n".join(long_line.format(n=n) for n in range(60))
    assert len(text) > notify.MAX_MESSAGE_LEN

    clamped = notify._clamp(text)

    assert len(clamped) <= notify.MAX_MESSAGE_LEN
    # every opening anchor still has its closing tag — nothing was cut mid-tag
    assert clamped.count("<a href=") == clamped.count("</a>")
    assert not clamped.rstrip(".").endswith("<a href=")


def test_clamp_leaves_a_short_message_untouched():
    assert notify._clamp("<b>hi</b>") == "<b>hi</b>"


def test_clamp_floor_case_strips_markup_from_one_oversized_line():
    """A single line longer than the cap has no line boundary to cut on. Rather than risk splitting
    a tag, the markup is stripped and a plain-text tail is delivered — degraded, but it arrives."""
    clamped = notify._clamp('<a href="https://e.com">' + "y" * (notify.MAX_MESSAGE_LEN + 500))

    assert len(clamped) <= notify.MAX_MESSAGE_LEN
    assert "<a href=" not in clamped
