from collections.abc import Callable
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from filmroom.api.engine_store import EngineStore
from filmroom.api.store import FixtureStore, Store
from filmroom.config import Settings
from filmroom.contracts.models import (
    CONTRACT_VERSION,
    Audience,
    Health,
    Match,
    MatchSummary,
    Narrative,
    PositionsChunk,
    Possession,
    PossessionSummary,
    Sliders,
    StyleConfig,
    StyleLens,
    Verdict,
)
from filmroom.style import load_lens, presets, public_lens, style_from_sliders, verdict

SliderQuery = Annotated[float | None, Query(ge=0, le=1)]


def _found[T](lookup: Callable[[], T]) -> T:
    try:
        return lookup()
    except KeyError as missing:
        raise HTTPException(status_code=404, detail=str(missing.args[0])) from missing


def create_app(store: Store, cors_origins: list[str]) -> FastAPI:
    app = FastAPI(title="FilmRoom API", version=CONTRACT_VERSION)
    app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_methods=["GET"], allow_headers=["*"])

    @app.get("/health")
    def health() -> Health:
        return Health(status="ok", contract_version=CONTRACT_VERSION, source=store.source)

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
    def narrative(
        possession_id: str, style: str, audience: Audience = "coach", language: str = "en"
    ) -> Narrative:
        return _found(lambda: store.narrative(possession_id, style, audience, language))

    return app


settings = Settings()
store = (
    EngineStore.from_settings(settings) if settings.store == "engine" else FixtureStore(settings.fixtures_dir)
)
app = create_app(store, settings.cors_origins)
