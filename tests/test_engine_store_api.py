import json

import pytest
from fastapi.testclient import TestClient

from filmroom.api.app import create_app
from filmroom.api.bundle import export_bundle
from filmroom.api.engine_store import EngineStore
from filmroom.contracts.models import (
    CONTRACT_VERSION,
    Narrative,
    PositionsChunk,
    Possession,
    StyleConfig,
    StyleLens,
    Verdict,
    template_slots,
)
from filmroom.engine.turning_point import EngineParams
from tests.engine_synth import SYNTH_MATCH, counter_attack
from tests.test_engine_analysis import FLAG_ALL, STYLES, constant_models

SLUG = "2000_01_01_009"


def _store(cache_dir=None, models=None, params=FLAG_ALL) -> EngineStore:
    md = counter_attack().build()
    return EngineStore(
        load=lambda match_id: md,
        match_ids=[SYNTH_MATCH],
        models=models or (lambda: {SYNTH_MATCH: constant_models()}),
        styles=STYLES,
        params=params,
        cache_dir=cache_dir,
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(_store(), cors_origins=[]))


def test_health_reports_the_engine_and_the_contract_version(client):
    assert client.get("/health").json() == {
        "status": "ok",
        "contract_version": CONTRACT_VERSION,
        "source": "engine",
        "llm": False,
    }
    assert CONTRACT_VERSION == "0.5.0"


def test_engine_store_serves_every_route(client):
    assert [m["id"] for m in client.get("/matches").json()] == [SLUG]
    assert len(client.get(f"/matches/{SLUG}").json()["players"]) == 22
    summaries = client.get(f"/matches/{SLUG}/possessions").json()
    assert [s["provenance"] for s in summaries] == ["engine"] * 3
    flagged = next(s for s in summaries if s["flagged"])
    possession = Possession.model_validate(client.get(f"/possessions/{flagged['id']}").json())
    assert possession.turning_point_idx is not None
    positions = PositionsChunk.model_validate(client.get(f"/possessions/{possession.id}/positions").json())
    assert positions.hz == 10 and positions.possession_id == possession.id
    params = {"style": STYLES[1].id, "audience": "coach", "language": "es"}
    narrative = Narrative.model_validate(
        client.get(f"/possessions/{possession.id}/narrative", params=params).json()
    )
    assert narrative.status == "template" and narrative.language == "es"
    assert narrative.claims[0].ref == possession.verdicts[STYLES[1].id].best_option_id
    assert template_slots(narrative.template) <= set(narrative.facts)


def test_unknown_ids_and_missing_narratives_return_404(client):
    assert client.get("/matches/nope").status_code == 404
    assert client.get("/matches/nope/possessions").status_code == 404
    assert client.get(f"/possessions/{SLUG}-99999").status_code == 404
    assert client.get("/possessions/nope-1").status_code == 404
    params = {"style": "nope", "audience": "coach", "language": "en"}
    assert client.get(f"/possessions/{SLUG}-0/narrative", params=params).status_code == 404
    params = {"style": STYLES[0].id, "audience": "coach", "language": "fr"}
    assert client.get(f"/possessions/{SLUG}-0/narrative", params=params).status_code == 422


def test_analyses_are_served_from_the_disk_cache_on_a_fresh_start(tmp_path):
    first = _store(cache_dir=tmp_path).possessions(SLUG)
    fits = []
    restarted = _store(cache_dir=tmp_path, models=lambda: fits.append(1) or {})
    assert restarted.possessions(SLUG) == first
    assert fits == []


def _flagged(client: TestClient) -> Possession:
    summary = next(s for s in client.get(f"/matches/{SLUG}/possessions").json() if s["flagged"])
    return Possession.model_validate(client.get(f"/possessions/{summary['id']}").json())


def test_styles_routes_serve_the_presets_and_the_lens(client):
    styles = [StyleConfig.model_validate(s) for s in client.get("/styles").json()]
    assert [s.id for s in styles] == [s.id for s in STYLES]
    lens = StyleLens.model_validate(client.get("/styles/lens").json())
    assert lens.reference_style_id == styles[0].id
    assert {spec.slider for spec in lens.sliders} == set(styles[0].sliders.model_dump())
    assert len(lens.rule_sets) == 6


def test_verdict_route_matches_the_stored_verdict_for_a_preset_and_its_sliders(client):
    possession = _flagged(client)
    for style in STYLES:
        stored = possession.verdicts[style.id]
        by_id = client.get(f"/possessions/{possession.id}/verdict", params={"style": style.id})
        assert Verdict.model_validate(by_id.json()) == stored
        custom = Verdict.model_validate(
            client.get(f"/possessions/{possession.id}/verdict", params=style.sliders.model_dump()).json()
        )
        assert custom.style_id == "custom"
        assert custom.model_dump(exclude={"style_id"}) == stored.model_dump(exclude={"style_id"})


def test_verdict_route_measures_the_flip_against_the_requested_style(client):
    possession = _flagged(client)
    params = {"style": STYLES[1].id, "vs": STYLES[1].id}
    same = Verdict.model_validate(client.get(f"/possessions/{possession.id}/verdict", params=params).json())
    assert same.flip_reason is None


def test_verdict_route_rejects_unknown_styles_unflagged_possessions_and_partial_sliders(client):
    possession = _flagged(client)
    route = f"/possessions/{possession.id}/verdict"
    assert client.get(route, params={"style": "nope"}).status_code == 404
    assert client.get(route, params={"style": STYLES[0].id, "vs": "nope"}).status_code == 404
    assert client.get(route, params={"risk_tolerance": 0.5}).status_code == 422
    assert client.get(route, params={**STYLES[0].sliders.model_dump(), "verticality": 2}).status_code == 422
    unflagged = TestClient(
        create_app(_store(params=EngineParams(flag_threshold=10.0, severity_scale=1.0)), [])
    )
    assert unflagged.get(route, params={"style": STYLES[0].id}).status_code == 404


def test_engine_bundle_exports_positions_for_every_possession_and_the_rest_only_for_flagged_ones(tmp_path):
    out = tmp_path / "bundle"
    flagged = export_bundle(_store(), out, public=False, match_ids=[SLUG])
    possessions = [f for f in flagged.files if f.startswith("possessions/") and f.count("/") == 1]
    assert len(possessions) == 3 and sum("/narrative/" in f for f in flagged.files) == 3 * 6 * 3 * 2
    assert [m["id"] for m in json.loads((out / "matches.json").read_text())] == [SLUG]

    unflagged = export_bundle(
        _store(params=EngineParams(flag_threshold=1e9, severity_scale=1)), out, public=False
    )
    assert sum(f.endswith("/positions.json") for f in unflagged.files) == 3
    assert not [f for f in unflagged.files if f.startswith("possessions/") and f.count("/") == 1]
    assert not [f for f in unflagged.files if "/narrative/" in f]


def test_engine_bundle_rejects_matches_the_store_does_not_have(tmp_path):
    with pytest.raises(KeyError, match="nope"):
        export_bundle(_store(), tmp_path / "bundle", public=True, match_ids=["nope"])


def test_positions_run_past_the_last_decision_so_the_turning_point_is_on_screen(client):
    for summary in client.get(f"/matches/{SLUG}/possessions").json():
        possession = Possession.model_validate(client.get(f"/possessions/{summary['id']}").json())
        chunk = PositionsChunk.model_validate(client.get(f"/possessions/{possession.id}/positions").json())
        shown_until = chunk.t0_ms + (len(chunk.xy) - 1) * 1000 / chunk.hz
        assert chunk.t0_ms <= possession.start_ms + 100
        assert shown_until >= max(d.t_ms for d in possession.decisions)
