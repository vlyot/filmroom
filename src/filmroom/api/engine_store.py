"""Engine-backed store: analyses a match on first request, with the models that never saw that match, and
caches the result on disk. Serves the same routes as FixtureStore."""

import hashlib
import json
from collections.abc import Callable
from functools import cache, cached_property
from pathlib import Path

from pydantic import TypeAdapter

from filmroom.agents.situations import similar_in
from filmroom.api.store import summary_of
from filmroom.config import Settings
from filmroom.contracts.models import (
    Match,
    MatchSummary,
    PositionsChunk,
    Possession,
    PossessionSummary,
    StyleConfig,
)
from filmroom.data.catalog import LOADER_VERSION, Catalog, MatchData, match_slug
from filmroom.engine import ENGINE_VERSION
from filmroom.engine.analyse import analyse_match
from filmroom.engine.assemble import match_view, possession_positions
from filmroom.engine.pass_model import EngineModels
from filmroom.engine.training import fit_lomo, load_rows
from filmroom.engine.turning_point import EngineParams, load_params
from filmroom.style import load_lens, presets

POSSESSIONS = TypeAdapter(list[Possession])


class EngineStore:
    source = "engine"

    def __init__(
        self,
        load: Callable[[str], MatchData],
        match_ids: list[str],
        models: Callable[[], dict[str, EngineModels]],
        styles: list[StyleConfig],
        params: EngineParams,
        cache_dir: Path | None = None,
    ):
        self._load = cache(load)
        self._ids = {match_slug(m): m for m in match_ids}
        self._fit_models = models
        self._styles = styles
        self._params = params
        self._analyses: dict[str, list[Possession]] = {}
        key = json.dumps([params.model_dump(), [s.model_dump() for s in styles]], sort_keys=True)
        version = f"e{ENGINE_VERSION}-l{LOADER_VERSION}-{hashlib.sha1(key.encode()).hexdigest()[:8]}"
        self._cache_dir = cache_dir / "engine" / f"analyses-{version}" if cache_dir else None

    @classmethod
    def from_settings(cls, settings: Settings) -> "EngineStore":
        catalog = Catalog(settings)
        return cls(
            load=catalog.load,
            match_ids=[m.id for m in catalog.matches()],
            models=lambda: fit_lomo(load_rows(catalog, settings.cache_dir)),
            styles=presets(load_lens()),
            params=load_params(),
            cache_dir=settings.cache_dir,
        )

    @cached_property
    def _models(self) -> dict[str, EngineModels]:
        return self._fit_models()

    def _md(self, slug: str) -> MatchData:
        if slug not in self._ids:
            raise KeyError(f"not found: {slug}")
        return self._load(self._ids[slug])

    def _possessions(self, slug: str) -> list[Possession]:
        if slug in self._analyses:
            return self._analyses[slug]
        md = self._md(slug)
        path = self._cache_dir / f"{slug}.json" if self._cache_dir else None
        if path and path.exists():
            possessions = POSSESSIONS.validate_json(path.read_bytes())
        else:
            models = self._models.get(md.info.id)  # matches with a broken event log have no models
            analyses = analyse_match(md, models, self._styles, self._params) if models else []
            possessions = [a.possession for a in analyses]
            if path:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(POSSESSIONS.dump_json(possessions))
        self._analyses[slug] = possessions
        return possessions

    def matches(self) -> list[MatchSummary]:
        return [MatchSummary.model_validate(self.match(s).model_dump(exclude={"players"})) for s in self._ids]

    def match(self, match_id: str) -> Match:
        return match_view(self._md(match_id))

    def possessions(self, match_id: str) -> list[PossessionSummary]:
        return [summary_of(p) for p in self._possessions(match_id)]

    def match_possessions(self, match_id: str) -> list[Possession]:
        return self._possessions(match_id)

    def possession(self, possession_id: str) -> Possession:
        slug = possession_id.rsplit("-", 1)[0]
        for p in self._possessions(slug) if slug in self._ids else []:
            if p.id == possession_id:
                return p
        raise KeyError(f"not found: {possession_id}")

    def positions(self, possession_id: str) -> PositionsChunk:
        p = self.possession(possession_id)
        return possession_positions(self._md(p.match_id), p)

    def similar(
        self, possession_id: str, style_id: str, k: int, all_matches: bool
    ) -> list[tuple[Possession, float]]:
        return similar_in(self, possession_id, style_id, k, all_matches)
