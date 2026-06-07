from app import lanes
from app.models import RadarItem


def _item(id_, title, summary="", source="news", meta=""):
    return RadarItem(id=id_, source=source, title=title, summary=summary, url="http://x", meta=meta)


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


def test_avoid_terms_drops_disliked_items():
    items = [
        _item(1, "LLM agents for crypto trading"),  # matches topic AND avoid -> dropped
        _item(2, "LLM agents for healthcare"),  # clean match -> kept
    ]
    avoid = lanes.avoid_terms({"avoid_topics": ["crypto", "NFT"]})
    out = lanes.curate(items, ["LLM", "agents"], avoid=avoid)

    assert [i.id for i in out] == [2]  # the crypto item is filtered out despite matching topics
