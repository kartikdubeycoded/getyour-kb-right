from app import lanes
from app.models import RadarItem


def _item(id_, title, summary="", source="news", meta=""):
    return RadarItem(id=id_, source=source, title=title, summary=summary, url="http://x", meta=meta)


def test_search_topics_merges_focus_and_lane_topics_deduped():
    profile = {
        "focus": "LLM, agents",
        "lanes": [
            {"name": "AI", "topics": ["agents", "RAG"]},  # "agents" already in focus -> deduped
            {"name": "Web Design", "topics": ["CSS", "UX"]},  # the thin lane's words get fetched
        ],
    }
    topics = lanes.search_topics(profile)
    assert topics[:2] == ["LLM", "agents"]  # focus topics come first, in order
    assert "RAG" in topics and "CSS" in topics and "UX" in topics  # lane topics included
    assert [t.lower() for t in topics].count("agents") == 1  # case-insensitive dedupe, no repeat


def test_search_topics_respects_cap_and_falls_back_to_focus():
    many = {"lanes": [{"name": f"L{i}", "topics": [f"t{i}"]} for i in range(20)], "focus": "AI"}
    assert len(lanes.search_topics(many, limit=5)) == 5  # capped

    no_lanes = {"focus": "machine learning, vision"}
    assert lanes.search_topics(no_lanes) == ["machine learning", "vision"]  # focus only


def test_lanes_from_profile_parses_and_falls_back():
    parsed = lanes.lanes_from_profile(
        {"lanes": [{"name": "AI", "topics": ["LLM", "agents"]}, {"name": "no-topics"}]}
    )
    assert parsed == [("AI", ["LLM", "agents"])]  # entry without topics is dropped

    fallback = lanes.lanes_from_profile({"focus": "web design, css"})
    assert fallback[0][0] == "All"  # never empty — falls back to a single lane from focus
    assert "web design" in fallback[0][1]


def test_curate_scores_filters_and_orders():
    items = [
        _item(1, "A guide to LLM agents", "build agents"),  # 2 topic hits
        _item(2, "Cooking pasta tonight"),  # 0 hits -> dropped
        _item(3, "New agents framework", source="github"),  # 1 hit
    ]
    out = lanes.curate(items, ["LLM", "agents"], limit=10)

    assert [i.id for i in out] == [1, 3]  # pasta dropped; higher score first
    assert out[0].source == "news" and out[1].source == "github"  # lane MIXES sources


def test_pulse_ranks_hottest_topics_across_all_lanes():
    profile = {
        "focus": "agents",
        "lanes": [
            {"name": "AI", "topics": ["agents", "RAG"]},
            {"name": "Systems", "topics": ["kubernetes"]},  # nothing mentions it -> drops
        ],
    }
    items = [
        _item(1, "agents everywhere", source="github"),
        _item(2, "more agents shipping", source="hn"),  # agents: 2 items, 2 sources
        _item(3, "a RAG pipeline", source="news"),  # RAG: 1 item, 1 source
    ]
    out = lanes.pulse(items, profile, top=5)

    assert out[0]["topic"] == "agents"  # broadest cross-source echo = top of the pulse
    topics = [r["topic"] for r in out]
    assert "RAG" in topics and "kubernetes" not in topics  # zero-mention topic dropped


def test_lane_signal_ranks_by_source_spread_then_volume():
    items = [
        _item(1, "LLM agents framework", source="github"),
        _item(2, "agents in production", source="hn"),
        _item(3, "the agents wave", source="news"),  # agents: 3 items, 3 distinct sources
        _item(4, "RAG tutorial", source="github"),
        _item(5, "RAG and retrieval", source="github"),  # RAG: 2 items, 1 source
    ]
    sig = lanes.lane_signal(items, ["agents", "RAG", "vision"])

    assert [r["topic"] for r in sig] == ["agents", "RAG"]  # vision (0 hits) dropped; agents leads
    assert sig[0]["sources"] == 3 and sig[0]["mentions"] == 3  # broad cross-source echo = hot
    assert sig[1]["sources"] == 1 and sig[1]["mentions"] == 2  # volume but only one source


def test_search_corpus_ranks_title_over_body_and_drops_misses():
    items = [
        _item(1, "Diffusion models explained", source="news"),  # term in TITLE
        _item(2, "A post about cats", summary="uses diffusion under the hood", source="hn"),  # body
        _item(3, "Totally unrelated", source="github"),  # no hit -> dropped
    ]
    out = lanes.search_corpus(items, "diffusion")

    assert [i.id for i in out] == [1, 2]  # title match outranks body match
    assert all(i.id != 3 for i in out)  # non-match dropped


def test_search_corpus_multi_term_and_empty_query():
    items = [_item(1, "RAG agents tutorial"), _item(2, "RAG only")]
    out = lanes.search_corpus(items, "rag agents")

    assert out[0].id == 1  # matches both terms -> outranks the single-term item
    assert lanes.search_corpus(items, "   ") == []  # empty/whitespace query -> no results


def test_avoid_terms_drops_disliked_items():
    items = [
        _item(1, "LLM agents for crypto trading"),  # matches topic AND avoid -> dropped
        _item(2, "LLM agents for healthcare"),  # clean match -> kept
    ]
    avoid = lanes.avoid_terms({"avoid_topics": ["crypto", "NFT"]})
    out = lanes.curate(items, ["LLM", "agents"], avoid=avoid)

    assert [i.id for i in out] == [2]  # the crypto item is filtered out despite matching topics
