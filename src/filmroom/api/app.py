import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query, WebSocket
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from filmroom.agents.facts import supported_languages
from filmroom.agents.layer import AgentLayer, narration_for
from filmroom.agents.overlay import overlay_events
from filmroom.agents.session_pack import PackRequest
from filmroom.api.replay import NARRATIVE_WAIT_S, ReplayChannel, ReplaySession
from filmroom.api.store import Store, open_store
from filmroom.config import Settings
from filmroom.contracts.models import (
    CONTRACT_VERSION,
    AnalystReply,
    AnalystRequest,
    Audience,
    Health,
    Match,
    MatchSummary,
    MetricsReport,
    Narrative,
    OverlayEvent,
    PositionsChunk,
    Possession,
    PossessionSummary,
    SessionPack,
    Sliders,
    StyleConfig,
    StyleLens,
    Verdict,
)
from filmroom.contracts.ws import ErrorMessage
from filmroom.monitoring import Metrics, timing
from filmroom.style import load_lens, presets, presets_by_id, public_lens, style_from_sliders, verdict

SliderQuery = Annotated[float | None, Query(ge=0, le=1)]


def _found[T](lookup: Callable[[], T]) -> T:
    try:
        return lookup()
    except KeyError as missing:
        raise HTTPException(status_code=404, detail=str(missing.args[0])) from missing


def _supported(language: str) -> str:
    if language not in (supported := supported_languages()):
        detail = f"unsupported language; supported: {', '.join(supported)}"
        raise HTTPException(status_code=422, detail=detail)
    return language


def create_app(
    store: Store, cors_origins: list[str], agents: AgentLayer | None = None, metrics: Metrics | None = None
) -> FastAPI:
    agents = agents or AgentLayer.offline(store)
    metrics = metrics or Metrics()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        with metrics.listening():
            async with agents.lifespan(app):
                yield

    app = FastAPI(title="FilmRoom API", version=CONTRACT_VERSION, lifespan=lifespan)
    app.middleware("http")(timing(metrics))
    app.add_middleware(
        CORSMiddleware, allow_origins=cors_origins, allow_methods=["GET", "POST"], allow_headers=["*"]
    )

    @app.get("/health")
    def health() -> Health:
        return Health(status="ok", contract_version=CONTRACT_VERSION, source=store.source, llm=agents.live)

    @app.get("/metrics")
    def metrics_report() -> MetricsReport:
        """Counters since start-up: requests, LLM calls, tokens against the daily cap and the monthly
        allowance, how often narratives and analyst replies fell back, and replay sockets."""
        return metrics.report(store.source, agents.narratives.budget)

    @app.get("/matches")
    def matches() -> list[MatchSummary]:
        return store.matches()

    @app.get("/matches/{match_id}")
    def match(match_id: str) -> Match:
        return _found(lambda: store.match(match_id))

    @app.get("/matches/{match_id}/possessions")
    def possessions(match_id: str) -> list[PossessionSummary]:
        return _found(lambda: store.possessions(match_id))

    @app.get("/possessions/{possession_id}")
    def possession(possession_id: str) -> Possession:
        return _found(lambda: store.possession(possession_id))

    @app.get("/possessions/{possession_id}/positions")
    def positions(possession_id: str) -> PositionsChunk:
        return _found(lambda: store.positions(possession_id))

    @app.get("/styles")
    def styles() -> list[StyleConfig]:
        return presets(load_lens())

    @app.get("/styles/lens")
    def lens() -> StyleLens:
        return public_lens(load_lens())

    @app.get("/possessions/{possession_id}/verdict")
    def possession_verdict(
        possession_id: str,
        style: str | None = None,
        vs: str | None = None,
        risk_tolerance: SliderQuery = None,
        verticality: SliderQuery = None,
        press_trigger: SliderQuery = None,
        line_height: SliderQuery = None,
    ) -> Verdict:
        """The turning-point verdict under a preset (`style`) or custom sliders (all four), with the flip
        reason measured against `vs` (the reference preset by default)."""
        lens = load_lens()
        named = {s.id: s for s in presets(lens)}
        reference = _found(lambda: named[vs or lens.presets[0].id])
        if style is not None:
            judged = _found(lambda: named[style])
        else:
            positions = {
                "risk_tolerance": risk_tolerance,
                "verticality": verticality,
                "press_trigger": press_trigger,
                "line_height": line_height,
            }
            if None in positions.values():
                raise HTTPException(status_code=422, detail="give a preset style or all four sliders")
            sliders = Sliders(**positions)
            judged = style_from_sliders(lens, reference.with_ball, reference.without_ball, sliders)
        possession = _found(lambda: store.possession(possession_id))
        if possession.turning_point_idx is None:
            raise HTTPException(status_code=404, detail=f"not flagged: {possession_id}")
        return verdict(possession.decisions[possession.turning_point_idx], judged, reference)

    @app.get("/possessions/{possession_id}/narrative")
    async def narrative(
        possession_id: str, style: str, audience: Audience = "coach", language: str = "en"
    ) -> Narrative:
        """The template at once (status `pending` while a verified narrative is generated), or the cached
        verified narrative. 404 for an unflagged possession or an unknown preset."""
        _supported(language)
        request = await run_in_threadpool(
            _found, lambda: agents.narration(possession_id, style, audience, language)
        )
        return agents.narratives.get(request)

    @app.post("/analyst")
    async def analyst(request: AnalystRequest) -> AnalystReply:
        """Ask the analyst about a match. It answers from the engine tools over MCP, writes no numbers and
        cites the possessions it talks about; status `offline` when no LLM is available."""
        _supported(request.language)
        if request.style_id is not None:
            _found(lambda: presets_by_id(load_lens())[request.style_id])
        if request.match_id is not None:
            await run_in_threadpool(_found, lambda: store.match(request.match_id))
        return await agents.analyst.answer(request)

    @app.get("/matches/{match_id}/session-pack")
    async def session_pack(
        match_id: str,
        team: Annotated[int, Query(ge=0, le=1)],
        style: str | None = None,
        period: Literal["half", "full"] = "full",
        audience: Audience = "coach",
        language: str = "en",
    ) -> SessionPack:
        """The team's top flagged moments for half-time (`half`: first-half moments) or full-time, grouped
        into themes, each with its narrative and how the other presets would judge it. Narratives not ready
        within about forty seconds come back as templates (status `pending`)."""
        style_id = style or load_lens().presets[0].id
        request = PackRequest(match_id, team, style_id, period, audience, _supported(language))
        try:
            return await agents.packs.build(request)
        except KeyError as missing:
            raise HTTPException(status_code=404, detail=str(missing.args[0])) from missing

    @app.get("/matches/{match_id}/overlay")
    async def overlay(match_id: str, style: str | None = None) -> list[OverlayEvent]:
        """One event per flagged moment under a preset (the reference by default), for broadcast graphics:
        when it happened, the chosen and best options, and a fan caption in every supported language. Serves
        cached verified captions or templates; never starts LLM work."""
        style_id = style or load_lens().presets[0].id
        match, possessions = await run_in_threadpool(
            _found, lambda: (store.match(match_id), store.match_possessions(match_id))
        )
        return _found(lambda: overlay_events(possessions, match, agents.narratives, style_id))

    @app.websocket("/matches/{match_id}/replay")
    async def replay(
        websocket: WebSocket,
        match_id: str,
        style: str | None = None,
        audience: Audience = "coach",
        language: str = "en",
        speed: float = 1.0,
        from_ms: int = 0,
    ) -> None:
        """Plays the match on a clock (speed 1–10): clock ticks, positions at 10 Hz and each flagged
        possession as the clock passes its end, with its narrative under `style`, `audience` and `language`.
        A pending narrative follows as a `narrative` message once generated. Control messages play, pause,
        seek (ms) and change speed."""
        await websocket.accept()
        channel = ReplayChannel(websocket)
        style_id = style or load_lens().presets[0].id
        try:
            if language not in supported_languages():
                raise KeyError(f"unsupported language: {language}")
            if style_id not in presets_by_id(load_lens()):
                raise KeyError(f"unknown style: {style_id}")
            match, possessions = await run_in_threadpool(
                lambda: (store.match(match_id), store.match_possessions(match_id))
            )
        except KeyError as missing:
            await channel.send([ErrorMessage(message=str(missing.args[0]))])
            await websocket.close(code=1008)
            return

        async def positions(possession_id: str) -> PositionsChunk | None:
            try:
                return await run_in_threadpool(store.positions, possession_id)
            except KeyError:
                return None

        def narrate(possession: Possession) -> Narrative:
            request = narration_for(possession, match, style_id, audience, language)
            narrative = agents.narratives.flagged(request)
            if narrative.status == "pending":
                channel.push_when_ready(agents.narratives.ready(request, NARRATIVE_WAIT_S))
            return narrative

        with metrics.replay():
            await channel.run(
                ReplaySession(possessions, match.duration_ms, positions, narrate, speed, from_ms)
            )

    app.router.routes.extend(agents.mcp_routes())
    return app


def _log_to_stdout() -> None:
    """One JSON line per LLM call and narrative, for Railway's logs."""
    logger = logging.getLogger("filmroom")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False  # FastMCP adds a root handler, which would print every line twice


settings = Settings()
store = open_store(settings)
_log_to_stdout()
app = create_app(store, settings.cors_origins, AgentLayer.from_settings(settings, store))
