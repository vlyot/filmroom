import asyncio

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from filmroom.agents.cache import JsonCache
from filmroom.agents.facts import render, supported_languages
from filmroom.agents.layer import AgentLayer, narration_for
from filmroom.agents.narratives import NarrativeService
from filmroom.api.app import create_app
from filmroom.api.replay import ReplaySession, slice_chunk
from filmroom.contracts.models import OverlayEvent, PositionsChunk
from filmroom.contracts.ws import (
    Clock,
    Control,
    ErrorMessage,
    MatchEnd,
    PositionsMessage,
    PossessionFlagged,
    ServerMessage,
)
from tests.agent_fakes import REFERENCE, STYLES, synth_store
from tests.test_narrative_service import RecordingNarrator

MATCH = "2000_01_01_009"  # 6,090 ms; flagged possessions end at 2,290, 3,990 and 5,790 ms


def _session(speed: float = 1.0, from_ms: int = 0, tracks: bool = True) -> ReplaySession:
    store = synth_store()

    async def positions(possession_id: str) -> PositionsChunk | None:
        return store.positions(possession_id) if tracks else None

    def narrate(possession):
        return narration_for(possession, store.match(MATCH), REFERENCE.id, "coach", "en").template()

    duration = store.match(MATCH).duration_ms
    return ReplaySession(store.match_possessions(MATCH), duration, positions, narrate, speed, from_ms)


def _advance(session: ReplaySession, *wall_ms: float) -> list:
    async def go():
        return [m for step in wall_ms for m in await session.advance(step)]

    return asyncio.run(go())


def _flagged(messages: list) -> list[str]:
    return [m.summary.id for m in messages if isinstance(m, PossessionFlagged)]


def test_the_clock_advances_by_wall_time_times_speed():
    session = _session(speed=2)
    messages = _advance(session, 0, 100)
    assert session.t_ms == 200
    assert [m.t_ms for m in messages if isinstance(m, Clock)] == [0, 200]


def test_a_paused_clock_holds_and_reports_once():
    session = _session()
    _advance(session, 0)
    session.control(Control(action="pause"))
    messages = _advance(session, 500, 500)
    assert session.t_ms == 0
    assert [m for m in messages if isinstance(m, Clock)] == [Clock(t_ms=0, speed=1.0, playing=False)]


def test_speed_is_clamped_between_one_and_ten():
    session = _session(speed=50)
    assert session.speed == 10
    session.control(Control(action="speed", value=0.2))
    assert session.speed == 1
    assert session.control(Control(action="speed")) == [ErrorMessage(message="speed needs a value")]


def test_each_flagged_possession_is_sent_once_after_its_end():
    session = _session(speed=10)
    assert _flagged(_advance(session, 0, 230)) == ["2000_01_01_009-0"]
    assert _flagged(_advance(session, 10)) == []
    assert _flagged(_advance(session, 200)) == ["2000_01_01_009-260"]


def test_a_forward_seek_sends_the_flags_it_skipped_and_a_backward_seek_resends_them():
    session = _session()
    session.control(Control(action="seek", value=5000))
    assert _flagged(_advance(session, 0)) == ["2000_01_01_009-0", "2000_01_01_009-260"]
    session.control(Control(action="seek", value=3000))
    session.control(Control(action="seek", value=4000))
    assert _flagged(_advance(session, 0)) == ["2000_01_01_009-260"]


def test_positions_go_out_in_one_second_slices_a_second_ahead_of_the_clock():
    session = _session()
    first = [m.chunk for m in _advance(session, 0) if isinstance(m, PositionsMessage)]
    assert [(c.t0_ms, len(c.xy)) for c in first] == [(0, 10)]
    following = [m.chunk for m in _advance(session, 100) if isinstance(m, PositionsMessage)]
    assert [(c.t0_ms, len(c.xy)) for c in following] == [(1000, 1)]


def test_possessions_without_a_track_send_no_positions():
    messages = _advance(_session(tracks=False), 0, 1000)
    assert not [m for m in messages if isinstance(m, PositionsMessage)]
    assert _flagged(messages) == []  # one second in, nothing has ended yet


def test_the_replay_ends_at_the_match_duration_and_play_restarts_it():
    session = _session(speed=10)
    messages = _advance(session, 0, 1000)
    assert session.t_ms == 6090 and not session.playing
    assert isinstance(messages[-1], MatchEnd)
    assert _advance(session, 100) == []
    session.control(Control(action="play"))
    assert session.t_ms == 0 and session.playing


def test_slice_chunk_keeps_rate_and_entities_and_cuts_rows_by_time():
    chunk = PositionsChunk(
        possession_id="p", t0_ms=1000, hz=10, pids=[128, 0], xy=[[i, 0, 0, 0] for i in range(20)]
    )
    part = slice_chunk(chunk, 1250, 1600)
    assert (part.t0_ms, part.hz, part.pids) == (1300, 10, [128, 0])
    assert [row[0] for row in part.xy] == [3, 4, 5]
    assert slice_chunk(chunk, 4000, 5000) is None


def _receive_until(ws, done) -> list:
    messages = []
    for _ in range(500):
        messages.append(ServerMessage.model_validate_json(ws.receive_text()).root)
        if done(messages):
            return messages
    raise AssertionError("the condition never held")


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(synth_store(), cors_origins=[]))


def test_replay_socket_streams_valid_clock_positions_flags_and_the_end(client):
    with client.websocket_connect(f"/matches/{MATCH}/replay?speed=10") as ws:
        messages = _receive_until(ws, lambda ms: isinstance(ms[-1], MatchEnd))
    kinds = {type(m) for m in messages}
    assert {Clock, PositionsMessage, PossessionFlagged, MatchEnd} <= kinds
    assert len(_flagged(messages)) == 3
    flag = next(m for m in messages if isinstance(m, PossessionFlagged))
    assert flag.narrative.style_id == REFERENCE.id and flag.narrative.status == "template"


def test_replay_socket_obeys_pause_seek_and_speed(client):
    url = f"/matches/{MATCH}/replay?style={STYLES[5].id}&audience=fan&language=es"
    with client.websocket_connect(url) as ws:
        ws.send_text(Control(action="pause").model_dump_json())
        _receive_until(ws, lambda ms: isinstance(ms[-1], Clock) and not ms[-1].playing)
        ws.send_text(Control(action="seek", value=4500).model_dump_json())
        messages = _receive_until(ws, lambda ms: len(_flagged(ms)) == 2)
        assert any(isinstance(m, Clock) and m.t_ms == 4500 for m in messages)
        flag = next(m for m in messages if isinstance(m, PossessionFlagged))
        assert (flag.narrative.audience, flag.narrative.language) == ("fan", "es")
        ws.send_text(Control(action="speed", value=4).model_dump_json())
        ws.send_text('{"type": "control", "action": "rewind"}')
        _receive_until(
            ws,
            lambda ms: (
                any(isinstance(m, ErrorMessage) for m in ms)
                and any(isinstance(m, Clock) and m.speed == 4 for m in ms)
            ),
        )


@pytest.mark.parametrize("query", ["/matches/nope/replay", f"/matches/{MATCH}/replay?style=nope"])
def test_replay_socket_reports_unknown_matches_and_styles_then_closes(client, query):
    with client.websocket_connect(query) as ws:
        assert isinstance(ServerMessage.model_validate_json(ws.receive_text()).root, ErrorMessage)
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()


def test_replay_socket_pushes_the_narrative_once_it_is_generated():
    store = synth_store()
    agents = AgentLayer.offline(store)
    agents.narratives = NarrativeService(RecordingNarrator(), JsonCache(None))
    with (
        TestClient(create_app(store, cors_origins=[], agents=agents)) as client,
        client.websocket_connect(f"/matches/{MATCH}/replay?from_ms=2500") as ws,
    ):
        messages = _receive_until(ws, lambda ms: any(m.type == "narrative" for m in ms))
    flag = next(m for m in messages if isinstance(m, PossessionFlagged))
    pushed = next(m for m in messages if m.type == "narrative")
    assert flag.narrative.status == "pending"
    assert pushed.narrative.possession_id == flag.summary.id and pushed.narrative.status == "verified"


def test_overlay_has_one_event_per_flagged_moment_with_a_caption_in_every_language(client):
    store = synth_store()
    match = store.match(MATCH)
    events = [OverlayEvent.model_validate(e) for e in client.get(f"/matches/{MATCH}/overlay").json()]
    assert len(events) == 3 and events == sorted(events, key=lambda e: e.t_ms)
    for event in events:
        possession = store.possession(event.possession_id)
        verdict = possession.verdicts[REFERENCE.id]
        assert event.t_ms == possession.decisions[verdict.decision_idx].t_ms
        assert (event.chosen_option_id, event.best_option_id) == (
            verdict.chosen_option_id,
            verdict.best_option_id,
        )
        assert set(event.captions) == set(supported_languages())
        for language, caption in event.captions.items():
            narrative = narration_for(possession, match, REFERENCE.id, "fan", language).template()
            assert caption == render(narrative.template, narrative.facts, language)


def test_overlay_follows_the_style_and_404s_for_unknown_ones(client):
    events = client.get(f"/matches/{MATCH}/overlay", params={"style": STYLES[5].id}).json()
    store = synth_store()
    assert [e["best_option_id"] for e in events] == [
        store.possession(e["possession_id"]).verdicts[STYLES[5].id].best_option_id for e in events
    ]
    assert client.get(f"/matches/{MATCH}/overlay", params={"style": "nope"}).status_code == 404
    assert client.get("/matches/nope/overlay").status_code == 404
