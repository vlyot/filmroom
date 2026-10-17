import json

import pytest
from fastapi.testclient import TestClient

from filmroom.api.app import create_app
from filmroom.api.bundle import export_bundle, route_to_path
from filmroom.api.store import FixtureStore
from filmroom.contracts import export
from filmroom.contracts.models import (
    CONTRACT_VERSION,
    BundleManifest,
    Match,
    MatchSummary,
    Narrative,
    PositionsChunk,
    Possession,
    PossessionSummary,
    StyleConfig,
    template_slots,
)
from filmroom.contracts.ws import ClientMessage, ServerMessage
from tests.conftest import REPO


def test_committed_contracts_match_the_code():
    assert (REPO / "contracts" / "schema.json").read_text(encoding="utf-8") == export.render(export.schema())
    assert (REPO / "contracts" / "openapi.json").read_text(encoding="utf-8") == export.render(
        export.openapi()
    )


def test_server_messages_discriminate_on_type():
    msg = ServerMessage.model_validate({"type": "clock", "t_ms": 1000, "speed": 2.0})
    assert type(msg.root).__name__ == "Clock"
    assert ClientMessage.model_validate({"type": "control", "action": "pause"}).root.action == "pause"


def test_template_slots_are_extracted():
    assert template_slots("At {tp.time}, {alt.player} was free ({alt.p_success})") == {
        "tp.time",
        "alt.player",
        "alt.p_success",
    }


@pytest.fixture
def client(mini_fixtures):
    return TestClient(create_app(FixtureStore(mini_fixtures), cors_origins=[]))


def test_every_get_route_returns_schema_valid_data(client):
    assert client.get("/health").json() == {
        "status": "ok",
        "contract_version": CONTRACT_VERSION,
        "source": "fixtures",
        "llm": False,
    }
    [summary] = [MatchSummary.model_validate(m) for m in client.get("/matches").json()]
    match = Match.model_validate(client.get(f"/matches/{summary.id}").json())
    assert len(match.players) == 22
    [pos_summary] = [
        PossessionSummary.model_validate(p) for p in client.get(f"/matches/{match.id}/possessions").json()
    ]
    possession = Possession.model_validate(client.get(f"/possessions/{pos_summary.id}").json())
    assert possession.provenance == "fixture"
    assert possession.decisions[possession.turning_point_idx].is_turning_point
    chunk = PositionsChunk.model_validate(client.get(f"/possessions/{possession.id}/positions").json())
    assert len(chunk.xy[0]) == 2 * len(chunk.pids)
    styles = [StyleConfig.model_validate(s) for s in client.get("/styles").json()]
    params = {"style": styles[0].id, "audience": "coach", "language": "en"}
    narrative = Narrative.model_validate(
        client.get(f"/possessions/{possession.id}/narrative", params=params).json()
    )
    assert narrative.status == "template" and template_slots(narrative.template) <= set(narrative.facts)


def test_unknown_ids_return_404(client):
    assert client.get("/matches/nope").status_code == 404
    assert client.get("/possessions/nope").status_code == 404
    assert client.get("/matches/nope/possessions").status_code == 404


def test_route_to_path_mirrors_routes():
    assert route_to_path("/matches") == "matches.json"
    assert route_to_path("/possessions/a-1/positions") == "possessions/a-1/positions.json"
    params = {"style": "s", "audience": "fan", "language": "es"}
    assert route_to_path("/possessions/a-1/narrative", params) == "possessions/a-1/narrative/s.fan.es.json"


def test_full_bundle_files_equal_their_route_responses(mini_fixtures, tmp_path, client):
    manifest = export_bundle(FixtureStore(mini_fixtures), tmp_path / "bundle", public=False)
    assert any(f.endswith("/positions.json") for f in manifest.files)
    assert {"styles.json", "styles/lens.json"} <= set(manifest.files)
    for rel in manifest.files:
        route = "/" + rel.removesuffix(".json")
        if "/narrative/" in rel:
            continue
        assert json.loads((tmp_path / "bundle" / rel).read_text(encoding="utf-8")) == client.get(route).json()


def test_public_bundle_has_no_positions_or_coordinates(mini_fixtures, tmp_path):
    out = tmp_path / "bundle"
    manifest = export_bundle(FixtureStore(mini_fixtures), out, public=True)
    assert manifest.public
    assert not any("positions" in f for f in manifest.files)
    for rel in manifest.files:
        if rel.startswith("possessions/") and rel.count("/") == 1:
            possession = Possession.model_validate_json((out / rel).read_bytes())
            assert all(o.target_xy is None for d in possession.decisions for o in d.options)
    assert BundleManifest.model_validate_json((out / "manifest.json").read_bytes()).files == manifest.files
