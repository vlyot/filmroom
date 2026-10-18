"""Data sources behind the API: FixtureStore serves files built by scripts/build_fixtures.py, EngineStore
analyses matches from the dataset, and DatabaseStore serves engine output seeded into Postgres (the deployed
API, which has no dataset). Lookups that find nothing raise KeyError, which the API turns into 404.
Narratives come from the agent layer, not the stores."""

from pathlib import Path
from typing import Protocol

from filmroom.agents.situations import similar_in
from filmroom.config import Settings
from filmroom.contracts.models import (
    Contract,
    Match,
    MatchSummary,
    PositionsChunk,
    Possession,
    PossessionSummary,
)


class FixturePossession(Contract):
    label_id: str | None
    possession: Possession
    positions: PositionsChunk


class Store(Protocol):
    source: str

    def matches(self) -> list[MatchSummary]: ...
    def match(self, match_id: str) -> Match: ...
    def possessions(self, match_id: str) -> list[PossessionSummary]: ...
    def match_possessions(self, match_id: str) -> list[Possession]: ...
    def possession(self, possession_id: str) -> Possession: ...
    def positions(self, possession_id: str) -> PositionsChunk: ...

    def similar(
        self, possession_id: str, style_id: str, k: int, all_matches: bool
    ) -> list[tuple[Possession, float]]:
        """The k flagged moments most like this one under a preset, from its match or every match, with their
        cosine similarity; most similar first, the possession itself left out."""
        ...


def open_store(settings: Settings) -> Store:
    """The store `settings.store` names. The engine and database stores are imported only when chosen, so
    the deployed API never loads the engine's training code and local runs never need a database driver."""
    if settings.store == "engine":
        from filmroom.api.engine_store import EngineStore

        return EngineStore.from_settings(settings)
    if settings.store == "database":
        from filmroom.api.db_store import DatabaseStore

        return DatabaseStore.from_settings(settings)
    return FixtureStore(settings.fixtures_dir)


def strip_coordinates(possession: dict) -> dict:
    """A possession's JSON for publishing without SoccER-derived positions: no option target coordinates."""
    for decision in possession["decisions"]:
        for option in decision["options"]:
            option["target_xy"] = None
    return possession


def summary_of(possession: Possession) -> PossessionSummary:
    return PossessionSummary.model_validate(
        possession.model_dump(include=set(PossessionSummary.model_fields))
    )


class FixtureStore:
    source = "fixtures"

    def __init__(self, root: Path):
        self.root = root

    def _read[M: Contract](self, path: Path, model: type[M]) -> M:
        if not path.exists():
            raise KeyError(f"not found: {path.stem}")
        return model.model_validate_json(path.read_text(encoding="utf-8"))

    def fixture(self, possession_id: str) -> FixturePossession:
        return self._read(self.root / "possessions" / f"{possession_id}.json", FixturePossession)

    def all_fixtures(self) -> list[FixturePossession]:
        return [self.fixture(p.stem) for p in sorted((self.root / "possessions").glob("*.json"))]

    def matches(self) -> list[MatchSummary]:
        return [
            MatchSummary.model_validate(self.match(p.stem).model_dump(exclude={"players"}))
            for p in sorted((self.root / "matches").glob("*.json"))
        ]

    def match(self, match_id: str) -> Match:
        return self._read(self.root / "matches" / f"{match_id}.json", Match)

    def possessions(self, match_id: str) -> list[PossessionSummary]:
        return [summary_of(p) for p in self.match_possessions(match_id)]

    def match_possessions(self, match_id: str) -> list[Possession]:
        self.match(match_id)
        return [f.possession for f in self.all_fixtures() if f.possession.match_id == match_id]

    def possession(self, possession_id: str) -> Possession:
        return self.fixture(possession_id).possession

    def positions(self, possession_id: str) -> PositionsChunk:
        return self.fixture(possession_id).positions

    def similar(
        self, possession_id: str, style_id: str, k: int, all_matches: bool
    ) -> list[tuple[Possession, float]]:
        return similar_in(self, possession_id, style_id, k, all_matches)
