import asyncio

from filmroom.agents.cache import JsonCache
from filmroom.agents.narratives import NarrativeService
from filmroom.agents.session_pack import PackRequest, SessionPackBuilder
from filmroom.style import flip_reason
from tests.agent_fakes import REFERENCE, STYLE_BY_ID, ScriptedChatClient, synth_store
from tests.test_narrative_service import RecordingNarrator

SLUG = "2000_01_01_009"
STORE = synth_store()


def _flagged(team: int | None = None):
    return [p for p in STORE.match_possessions(SLUG) if p.flagged and team in (None, p.team)]


def _build(request: PackRequest, replies=None, narrator=None):
    client = ScriptedChatClient(replies) if replies is not None else None
    narratives = NarrativeService(narrator, JsonCache(None))
    builder = SessionPackBuilder(STORE, narratives, client, "scripted-model", JsonCache(None))

    async def go():
        narratives.start()
        try:
            return await builder.build(request)
        finally:
            await narratives.stop()

    return asyncio.run(go()), client


def _request(team: int, period="full", style=REFERENCE.id, language="en") -> PackRequest:
    return PackRequest(SLUG, team, style, period, "coach", language)


def test_picks_the_teams_flagged_moments_most_severe_first():
    team = _flagged()[0].team
    pack, _ = _build(_request(team))
    expected = sorted(_flagged(team), key=lambda p: (-p.severity, p.start_ms))
    assert [m.summary.id for m in pack.moments] == [p.id for p in expected]
    assert [m.rank for m in pack.moments] == list(range(1, len(expected) + 1))
    assert all(m.summary.team == team for m in pack.moments)


def test_a_half_time_pack_keeps_only_first_half_moments():
    team = _flagged()[0].team
    half = STORE.match(SLUG).duration_ms / 2
    pack, _ = _build(_request(team, period="half"))
    assert [m.summary.id for m in pack.moments] == [
        p.id for p in sorted(_flagged(team), key=lambda p: (-p.severity, p.start_ms)) if p.start_ms < half
    ]


def test_groups_moments_into_verified_themes():
    team = _flagged()[0].team
    ids = [p.id for p in sorted(_flagged(team), key=lambda p: (-p.severity, p.start_ms))]
    themes = {
        "themes": [
            {"title": "Forcing it in midfield", "summary": "Look for the safer pass.", "possession_ids": ids}
        ]
    }
    pack, client = _build(_request(team), replies=[themes])
    assert [(t.title, t.status, t.possession_ids) for t in pack.themes] == [
        ("Forcing it in midfield", "verified", ids)
    ]
    assert len(client.requests) == 1


def test_falls_back_to_outcome_and_zone_themes_when_the_agent_fails_twice():
    team = _flagged()[0].team
    bad = {"themes": [{"title": "Two errors", "summary": "Lost 3 times.", "possession_ids": ["nope-1"]}]}
    pack, client = _build(_request(team, language="es"), replies=[bad, bad])
    assert len(client.requests) == 2
    assert all(t.status == "fallback" for t in pack.themes)
    assert sorted(i for t in pack.themes for i in t.possession_ids) == sorted(p.id for p in _flagged(team))
    assert {m.summary.outcome for m in pack.moments} == {t.title.split(",")[0] for t in pack.themes} or all(
        "," in t.title for t in pack.themes
    )


def test_counts_style_shifts_as_the_engine_judges_them():
    team = _flagged()[0].team
    pack, _ = _build(_request(team, style="direct-mid-block"))
    active = STYLE_BY_ID["direct-mid-block"]
    assert [s.style_id for s in pack.style_shifts] == [s for s in STYLE_BY_ID if s != active.id]
    for shift in pack.style_shifts:
        flips = [
            flip_reason(p.decisions[p.turning_point_idx], active, STYLE_BY_ID[shift.style_id])
            for p in _flagged(team)
        ]
        assert shift.changed == sum(f is not None for f in flips)
        assert (shift.factor is None) == (shift.changed == 0)


def test_narrates_each_moment_and_keeps_templates_without_an_llm():
    team = _flagged()[0].team
    narrated, _ = _build(_request(team), narrator=RecordingNarrator())
    assert {m.narrative.status for m in narrated.moments} == {"verified"}
    offline, _ = _build(_request(team))
    assert {m.narrative.status for m in offline.moments} == {"template"}
    assert all(m.narrative.possession_id == m.summary.id for m in offline.moments)
    assert all(
        m.verdict == next(p for p in _flagged() if p.id == m.summary.id).verdicts[REFERENCE.id]
        for m in offline.moments
    )
