from collections.abc import Callable

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

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
    StyleConfig,
)


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
        return store.styles()

    @app.get("/possessions/{possession_id}/narrative")
    def narrative(
        possession_id: str, style: str, audience: Audience = "coach", language: str = "en"
    ) -> Narrative:
        return _found(lambda: store.narrative(possession_id, style, audience, language))

    return app


settings = Settings()
app = create_app(FixtureStore(settings.fixtures_dir), settings.cors_origins)
