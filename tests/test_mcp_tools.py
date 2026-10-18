import asyncio
import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from filmroom.agents.mcp_server import build_mcp
from filmroom.agents.situations import situation_vector
from filmroom.agents.tools import EngineTools
from filmroom.style import best_option, flip_reason
from tests.agent_fakes import REFERENCE, STYLES, synth_store

SLUG = "2000_01_01_009"


@pytest.fixture(scope="module")
def tools() -> EngineTools:
    return EngineTools(synth_store())


def _flagged(tools: EngineTools):
    return [p for p in tools.store.match_possessions(SLUG) if p.flagged]


def test_exposes_the_six_engine_tools_with_schemas_over_mcp(tools):
    async def go():
        async with create_connected_server_and_client_session(build_mcp(tools)._mcp_server) as session:
            listed = (await session.list_tools()).tools
            result = await session.call_tool("list_flagged_moments", {"match_id": SLUG, "limit": 2})
            missing = await session.call_tool("get_possession", {"possession_id": "nope-1"})
            return listed, result, missing

    listed, result, missing = asyncio.run(go())
    assert {t.name: set(t.inputSchema["properties"]) for t in listed} == {
        "list_flagged_moments": {"match_id", "team", "style_id", "outcome", "zone", "limit"},
        "get_possession": {"possession_id"},
        "find_turning_point": {"possession_id", "style_id"},
        "evaluate_options": {
            "possession_id", "style_id", "risk_tolerance", "verticality", "press_trigger", "line_height",
            "decision_idx",
        },
        "compare_styles": {"possession_id", "style_a", "style_b"},
        "search_similar_situations": {"possession_id", "limit", "all_matches"},
    }  # fmt: skip
    assert all(t.annotations.readOnlyHint and t.description for t in listed)
    assert not result.isError and len(result.structuredContent["result"]) == 2
    assert missing.isError and "unknown possession nope-1" in missing.content[0].text


def test_lists_flagged_moments_by_severity_with_filters(tools):
    rows = tools.list_flagged_moments(SLUG)
    assert [r.severity for r in rows] == sorted((r.severity for r in rows), reverse=True)
    assert {r.possession_id for r in rows} == {p.id for p in _flagged(tools)}
    assert all(r.team == 0 for r in tools.list_flagged_moments(SLUG, team=0))
    assert [r.outcome for r in tools.list_flagged_moments(SLUG, outcome="shot")] == ["shot"]
    assert len(tools.list_flagged_moments(SLUG, limit=1)) == 1
    with pytest.raises(ValueError, match="unknown match"):
        tools.list_flagged_moments("nope")


def test_option_ranking_matches_the_engines_best_option_under_every_preset(tools):
    for possession in _flagged(tools):
        decision = possession.decisions[possession.turning_point_idx]
        for style in STYLES:
            view = tools.evaluate_options(possession.id, style.id)
            assert view.options[0].option_id == best_option(decision, style).id
            assert sum(o.chosen for o in view.options) == 1


def test_evaluates_options_under_custom_sliders(tools):
    possession = _flagged(tools)[0]
    view = tools.evaluate_options(
        possession.id, risk_tolerance=1.0, verticality=1.0, press_trigger=0.0, line_height=0.0
    )
    assert view.style == "custom"
    with pytest.raises(ValueError, match="decisions 0 to"):
        tools.evaluate_options(possession.id, decision_idx=99)


def test_style_comparison_names_the_engines_flip_factor_and_its_slider(tools):
    for possession in _flagged(tools):
        decision = possession.decisions[possession.turning_point_idx]
        for style in STYLES[1:]:
            comparison = tools.compare_styles(possession.id, REFERENCE.id, style.id)
            flip = flip_reason(decision, REFERENCE, style)
            assert comparison.same_verdict == (flip is None)
            assert comparison.factor == (flip.factor if flip else None)
            if flip:
                assert comparison.slider is not None and comparison.b.principle is not None


def test_turning_point_reports_the_verdict_and_flip_under_a_style(tools):
    possession = _flagged(tools)[0]
    view = tools.find_turning_point(possession.id, "direct-mid-block")
    verdict = possession.verdicts["direct-mid-block"]
    assert (view.best_option_id, view.better_available) == (verdict.best_option_id, verdict.better_available)
    assert view.flip.factor == verdict.flip_reason.factor and view.flip.slider == "verticality"
    with pytest.raises(ValueError, match="unknown style"):
        tools.find_turning_point(possession.id, "nope")


def test_similar_situations_leave_out_the_query_and_are_deterministic(tools):
    target = _flagged(tools)[0]
    similar = tools.search_similar_situations(target.id, limit=5)
    assert target.id not in {s.possession_id for s in similar}
    assert [s.similarity for s in similar] == sorted((s.similarity for s in similar), reverse=True)
    assert similar == tools.search_similar_situations(target.id, limit=5, all_matches=True)
    assert len(situation_vector(target, REFERENCE.id)) == 3 + 3 + 3 + 8 + 8


def test_similar_situations_ask_the_store_under_the_reference_style(tools):
    calls = []

    class Recording:
        def __getattr__(self, name):
            return getattr(tools.store, name)

        def similar(self, *args):
            calls.append(args)
            return tools.store.similar(*args)

    target = _flagged(tools)[0]
    found = EngineTools(Recording()).search_similar_situations(target.id, limit=40, all_matches=True)
    assert calls == [(target.id, REFERENCE.id, 25, True)]
    assert found == tools.search_similar_situations(target.id, limit=40, all_matches=True)


def test_tool_results_serialise_to_json(tools):
    possession = _flagged(tools)[0]
    json.dumps(tools.get_possession(possession.id).model_dump())
    assert tools.get_possession(possession.id).decisions[-1].is_turning_point
