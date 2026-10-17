import logging
from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from filmroom.agents.facts import supported_languages
from filmroom.agents.layer import AgentLayer
from filmroom.agents.session_pack import PackRequest
from filmroom.api.engine_store import EngineStore
from filmroom.api.store import FixtureStore, Store
from filmroom.config import Settings
from filmroom.contracts.models import (
    CONTRACT_VERSION,
    AnalystReply,
    AnalystRequest,
    Audience,
    Health,
    Match,
    MatchSummary,
    Narrative,
    PositionsChunk,
    Possession,
    PossessionSummary,
    SessionPack,
    Sliders,
    StyleConfig,
    StyleLens,
    Verdict,
)
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


def create_app(store: Store, cors_origins: list[str], agents: AgentLayer | None = None) -> FastAPI:
    agents = agents or AgentLayer.offline(store)
    app = FastAPI(title="FilmRoom API", version=CONTRACT_VERSION, lifespan=agents.lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=cors_origins, allow_methods=["GET", "POST"], allow_headers=["*"]
    )

    @app.get("/health")
    def health() -> Health:
        return Health(status="ok", contract_version=CONTRACT_VERSION, source=store.source, llm=agents.live)

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
store = (
    EngineStore.from_settings(settings) if settings.store == "engine" else FixtureStore(settings.fixtures_dir)
)
_log_to_stdout()
app = create_app(store, settings.cors_origins, AgentLayer.from_settings(settings, store))
