"""Data sources behind the API. FixtureStore serves files built by scripts/build_fixtures.py; a database store
replaces it in Phase 5. Lookups that find nothing raise KeyError, which the API turns into 404."""

from pathlib import Path
from typing import Protocol

from filmroom.contracts.models import (
    Audience,
    Contract,
    Match,
    MatchSummary,
    Narrative,
    PositionsChunk,
    Possession,
    PossessionSummary,
)


class FixturePossession(Contract):
    label_id: str | None
    possession: Possession
    positions: PositionsChunk
    narratives: list[Narrative]


class Store(Protocol):
    source: str

    def matches(self) -> list[MatchSummary]: ...
    def match(self, match_id: str) -> Match: ...
    def possessions(self, match_id: str) -> list[PossessionSummary]: ...
    def possession(self, possession_id: str) -> Possession: ...
    def positions(self, possession_id: str) -> PositionsChunk: ...
    def narrative(self, possession_id: str, style: str, audience: Audience, language: str) -> Narrative: ...


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
        self.match(match_id)
        return [summary_of(f.possession) for f in self.all_fixtures() if f.possession.match_id == match_id]

    def possession(self, possession_id: str) -> Possession:
        return self.fixture(possession_id).possession

    def positions(self, possession_id: str) -> PositionsChunk:
        return self.fixture(possession_id).positions

    def narrative(self, possession_id: str, style: str, audience: Audience, language: str) -> Narrative:
        for n in self.fixture(possession_id).narratives:
            if (n.style_id, n.audience, n.language) == (style, audience, language):
                return n
        raise KeyError(f"no narrative for {possession_id} / {style} / {audience} / {language}")
