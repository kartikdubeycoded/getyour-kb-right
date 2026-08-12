"""The opportunity radar's job is filtering, not fetching: a deadline you can't hit and an entry
that has nothing to do with you are both noise. These tests pin that judgement, with the network
faked — no key, no calls."""

import json
from datetime import UTC, datetime, timedelta

from app import opportunity_radar as opps

PROFILE = {"focus": "AI engineering, agents"}


def _devpost(**over):
    row = {
        "title": "Agent Hack",
        "url": "https://agent-hack.devpost.com/",
        "time_left_to_submission": "12 days left",
        "prize_amount": "$<span data-currency-value>5,000</span>",
        "themes": [{"name": "Machine Learning/AI"}],
        "displayed_location": {"location": "Online"},
        "registrations_count": 40,
        "submission_period_dates": "Jul 1 - Aug 20, 2026",
        "invite_only": False,
    }
    row.update(over)
    return row


def _unstop(**over):
    row = {
        "title": "College Hackfest",
        "public_url": "hackathons/college-hackfest-123",
        "end_date": (datetime.now(UTC) + timedelta(days=9)).isoformat(),
        "organisation": {"name": "Some College"},
        "details": "<p>Build an <strong>AI</strong> project</p>",
        "region": "online",
    }
    row.update(over)
    return row


def _fake_net(monkeypatch, devpost_rows=(), unstop_rows=()):
    """Route both hosts to canned payloads so no request leaves the machine."""

    def fake(url: str) -> dict:
        if url.startswith(opps.DEVPOST_URL):
            return {"hackathons": list(devpost_rows)}
        return {"data": {"data": list(unstop_rows)}}

    monkeypatch.setattr(opps, "_get_json", fake)


def test_builds_items_from_both_sources_with_deadline_in_the_meta(monkeypatch):
    _fake_net(monkeypatch, [_devpost()], [_unstop()])

    items = opps.fetch_opportunities(PROFILE, per_source=1)

    assert {i.source for i in items} == {"opps"}
    devpost = next(i for i in items if "devpost.com" in i.url)
    assert "12 days left" in devpost.meta and "$5,000" in devpost.meta
    unstop = next(i for i in items if "unstop.com" in i.url)
    assert (
        unstop.url == "https://unstop.com/hackathons/college-hackfest-123"
    )  # relative -> absolute
    assert "days left" in unstop.meta
    assert "<strong>" not in (unstop.summary or "")  # HTML stripped out of the description


def test_drops_entries_that_are_closed_or_too_soon_to_enter(monkeypatch):
    _fake_net(
        monkeypatch,
        [
            _devpost(title="Closing tonight", time_left_to_submission="about 3 hours left"),
            _devpost(title="Real one", url="https://real.devpost.com/"),
        ],
        [
            _unstop(
                title="Already over", end_date=(datetime.now(UTC) - timedelta(days=2)).isoformat()
            )
        ],
    )

    titles = [i.title for i in opps.fetch_opportunities(PROFILE, per_source=1)]

    assert titles == ["Real one"]  # a deadline you cannot build for is not an opportunity


def test_relevance_outranks_a_nearer_deadline(monkeypatch):
    """The whole point of ranking: an AI hackathon three weeks out beats a generic one closing
    Friday, because that's the one he'd actually enter."""
    _fake_net(
        monkeypatch,
        [
            _devpost(
                title="Generic Buildathon",
                url="https://generic.devpost.com/",
                themes=[{"name": "Open Ended"}],
                time_left_to_submission="4 days left",
            ),
            _devpost(
                title="AI Agent Challenge",
                url="https://ai.devpost.com/",
                themes=[{"name": "Machine Learning/AI"}],
                time_left_to_submission="21 days left",
            ),
        ],
    )

    items = sorted(opps.fetch_opportunities(PROFILE, per_source=1), key=lambda i: -i.score)

    assert items[0].title == "AI Agent Challenge"


def test_invite_only_entries_are_dropped(monkeypatch):
    _fake_net(monkeypatch, [_devpost(invite_only=True)])
    assert opps.fetch_opportunities(PROFILE, per_source=1) == []


def test_zero_prize_is_omitted_rather_than_shown_as_zero(monkeypatch):
    _fake_net(monkeypatch, [_devpost(prize_amount="$<span data-currency-value>0</span>")])
    assert "🏆" not in opps.fetch_opportunities(PROFILE, per_source=1)[0].meta


def test_one_dead_source_never_sinks_the_other(monkeypatch):
    def half_dead(url: str) -> dict:
        if url.startswith(opps.UNSTOP_URL):
            raise opps.RadarError("unstop down")
        return {"hackathons": [_devpost()]}

    monkeypatch.setattr(opps, "_get_json", half_dead)

    assert [i.title for i in opps.fetch_opportunities(PROFILE, per_source=1)] == ["Agent Hack"]


def test_devpost_searches_the_lane_topics_not_just_the_focus_line(monkeypatch):
    asked: list[str] = []

    def capture(url: str) -> dict:
        asked.append(url)
        return {"hackathons": []}

    monkeypatch.setattr(opps, "_get_json", capture)
    opps.fetch_opportunities(PROFILE, topics=["web design", "robotics"], per_source=4)

    joined = " ".join(asked)
    assert "web+design" in joined or "web%20design" in joined  # lane topic drove the query
    assert "robotics" in joined


def test_days_from_phrase_reads_devposts_human_wording():
    assert opps._days_from_phrase("about 1 month left") == 30.0
    assert opps._days_from_phrase("2 weeks left") == 14.0
    assert opps._days_from_phrase("6 days left") == 6.0
    assert opps._days_from_phrase("") is None  # unknown shape -> dropped, never guessed


def test_keywords_broadens_phrases_so_short_titles_can_match():
    words = opps._keywords(["multi-agent systems", "and systems design."])
    assert "agent" in words and "multi-agent systems" in words
    assert "and" not in words  # stopwords never become a match term


def test_parses_a_verbatim_live_devpost_row(monkeypatch):
    """An untouched row captured from the real API on 30 Jul 2026. If Devpost renames a field,
    this fails loudly here instead of the tab quietly going empty in the browser."""
    row = json.loads(
        '{"id":30366,"title":"Next Byte Hacks V3","displayed_location":{"icon":"globe",'
        '"location":"Online"},"open_state":"open","url":"https://next-byte-hacks-v3.devpost.com/",'
        '"time_left_to_submission":"9 days left","submission_period_dates":"Jun 15 - Aug 8, 2026",'
        '"themes":[{"id":23,"name":"Beginner Friendly"}],'
        '"prize_amount":"$<span data-currency-value>1,000</span>","prizes_counts":{"cash":0},'
        '"registrations_count":504,"organization_name":"Next Bytes","invite_only":false}'
    )
    _fake_net(monkeypatch, [row])

    item = opps.fetch_opportunities(PROFILE, per_source=1)[0]

    assert item.title == "Next Byte Hacks V3"
    assert item.url == "https://next-byte-hacks-v3.devpost.com/"
    assert "⏳ 9 days left" in item.meta and "🏆 $1,000" in item.meta and "Devpost" in item.meta
    assert "Beginner Friendly" in item.summary and "504 registered" in item.summary
