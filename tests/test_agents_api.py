import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from filmroom.agents.analyst import Analyst, http_tools
from filmroom.agents.cache import JsonCache
from filmroom.agents.layer import AgentLayer
from filmroom.agents.mcp_server import build_mcp
from filmroom.agents.narratives import NarrativeService
from filmroom.agents.session_pack import SessionPackBuilder
from filmroom.agents.tools import EngineTools
from filmroom.api.app import create_app
from filmroom.api.bundle import export_bundle
from filmroom.api.store import FixtureStore
from filmroom.contracts.models import AnalystReply, Narrative, SessionPack
from filmroom.style import load_lens, presets_by_id
from tests.agent_fakes import REFERENCE, ScriptedChatClient, ToolCall, synth_store
from tests.test_narrative_service import RecordingNarrator

SLUG = "2000_01_01_009"
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def _layer(store, narrator=None, client=None, mcp_url: str | None = None) -> AgentLayer:
    narratives = NarrativeService(narrator, JsonCache(None))
    tools = http_tools(mcp_url) if mcp_url else None
    return AgentLayer(
        store,
        narratives,
        Analyst(client, "scripted-model", store, tools),
        SessionPackBuilder(store, narratives, client, "scripted-model", JsonCache(None)),
        build_mcp(EngineTools(store)),
    )


def _flagged_id(store) -> str:
    return next(p.id for p in store.match_possessions(SLUG) if p.flagged)


def test_narrative_route_returns_the_template_at_once_then_the_verified_narrative():
    store = synth_store()
    app = create_app(store, [], _layer(store, narrator=RecordingNarrator()))
    params = {"style": REFERENCE.id, "audience": "fan", "language": "es"}
    with TestClient(app) as client:
        assert client.get("/health").json()["llm"] is True
        url = f"/possessions/{_flagged_id(store)}/narrative"
        first = Narrative.model_validate(client.get(url, params=params).json())
        for _ in range(100):
            later = Narrative.model_validate(client.get(url, params=params).json())
            if later.status == "verified":
                break
            time.sleep(0.02)
    assert first.status == "pending" and later.status == "verified"
    assert later.template == first.template and later.language == "es"


def test_offline_api_reports_no_llm_and_an_offline_analyst():
    store = synth_store()
    client = TestClient(create_app(store, []))
    assert client.get("/health").json()["llm"] is False
    body = {"question": "Where did we lose it?", "match_id": SLUG, "language": "es"}
    reply = AnalystReply.model_validate(client.post("/analyst", json=body).json())
    assert reply.status == "offline" and reply.text.startswith("El analista")
    assert client.post("/analyst", json=body | {"match_id": "nope"}).status_code == 404
    assert client.post("/analyst", json=body | {"style_id": "nope"}).status_code == 404
    assert client.post("/analyst", json=body | {"language": "fr"}).status_code == 422
    assert client.post("/analyst", json=body | {"question": "x" * 501}).status_code == 422


def test_session_pack_route_returns_a_pack_and_validates_its_inputs():
    store = synth_store()
    client = TestClient(create_app(store, []))
    team = next(p.team for p in store.match_possessions(SLUG) if p.flagged)
    response = client.get(f"/matches/{SLUG}/session-pack", params={"team": team, "language": "es"})
    pack = SessionPack.model_validate(response.json())
    assert pack.style_id == REFERENCE.id and pack.moments and pack.themes
    assert {m.narrative.status for m in pack.moments} == {"template"}
    assert client.get("/matches/nope/session-pack", params={"team": 0}).status_code == 404
    assert client.get(f"/matches/{SLUG}/session-pack", params={"team": 0, "style": "nope"}).status_code == 404
    assert client.get(f"/matches/{SLUG}/session-pack", params={"team": 2}).status_code == 422


def _rpc(request_id: int, method: str, params: dict | None = None) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "method": method} | ({"params": params} if params else {})


def test_serves_the_engine_tools_over_mcp_at_slash_mcp():
    store = synth_store()
    call = {"name": "find_turning_point", "arguments": {"possession_id": _flagged_id(store)}}
    with TestClient(create_app(store, [])) as client:
        listed = client.post("/mcp", json=_rpc(1, "tools/list"), headers=MCP_HEADERS)
        called = client.post("/mcp", json=_rpc(2, "tools/call", call), headers=MCP_HEADERS)
    assert len(listed.json()["result"]["tools"]) == 6
    result = called.json()["result"]
    assert not result["isError"] and result["structuredContent"]["possession_id"] == _flagged_id(store)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_the_analyst_reaches_the_engine_through_the_apis_own_mcp_endpoint():
    store, port = synth_store(), _free_port()
    pid = _flagged_id(store)
    replies = [
        ToolCall("find_turning_point", {"possession_id": pid}),
        {"text": "The move broke down on a forced pass.", "possession_ids": [pid]},
    ]
    llm = ScriptedChatClient(replies)
    app = create_app(store, [], _layer(store, client=llm, mcp_url=f"http://127.0.0.1:{port}/mcp"))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(200):
            if server.started:
                break
            time.sleep(0.02)
        body = {"question": "Why was it flagged?", "match_id": SLUG}
        response = httpx.post(f"http://127.0.0.1:{port}/analyst", json=body, timeout=30)
        reply = AnalystReply.model_validate(response.json())
    finally:
        server.should_exit = True
        thread.join(5)
    assert reply.status == "verified" and reply.possession_ids == [pid]
    results = [c.result for m in llm.requests[1] for c in m.contents if c.type == "function_result"]
    assert pid in json.dumps(results, default=str)


@pytest.fixture
def mini_store(mini_fixtures) -> FixtureStore:
    return FixtureStore(mini_fixtures)


def test_bundle_exports_every_narrative_preferring_cached_verified_ones(mini_store, tmp_path):
    possession = mini_store.all_fixtures()[0].possession
    cache = JsonCache(tmp_path / "agents")
    agents = AgentLayer.offline(mini_store, cache, "m")
    request = agents.narration(possession.id, REFERENCE.id, "coach", "en")
    cache.put(request.cache_key("m"), request.template().model_copy(update={"status": "verified"}))
    manifest = export_bundle(mini_store, tmp_path / "bundle", public=True, agents=agents)
    narratives = [f for f in manifest.files if "/narrative/" in f]
    assert len(narratives) == len(presets_by_id(load_lens())) * 3 * 2
    statuses = {
        f: Narrative.model_validate_json((tmp_path / "bundle" / f).read_bytes()).status for f in narratives
    }
    verified = [f for f, status in statuses.items() if status == "verified"]
    assert verified == [f"possessions/{possession.id}/narrative/{REFERENCE.id}.coach.en.json"]
    assert set(statuses.values()) == {"verified", "template"}
