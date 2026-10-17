"""Fill the narrative cache for the demo possessions before recording or exporting the bundle.

Every call draws on the $10 monthly Mistral allowance, so it first prints how many calls it would make
(cached narratives are skipped) and what they would cost, and spends only with --yes.

Usage:
  uv run python scripts/prewarm_narratives.py --possessions ID [ID ...] [--yes]
  uv run python scripts/prewarm_narratives.py --match 2019_09_09_001 --top 5 [--yes]
Options: --styles / --audiences / --languages narrow the set (default: every preset, audience and language).
"""

import argparse
import asyncio
from collections import Counter
from typing import get_args

from filmroom.agents.facts import supported_languages
from filmroom.agents.layer import AgentLayer
from filmroom.agents.narrator import NarrationRequest
from filmroom.api.engine_store import EngineStore
from filmroom.api.store import FixtureStore
from filmroom.config import Settings
from filmroom.contracts.models import Audience, Narrative
from filmroom.style import load_lens, presets_by_id

# Measured on a live narrator call (about 900 tokens in, 100 out), with headroom for retries; Mistral Small 4
# costs $0.15 / $0.60 per million tokens in / out.
TOKENS_IN, TOKENS_OUT = 1200, 150
COST_PER_CALL = (TOKENS_IN * 0.15 + TOKENS_OUT * 0.60) / 1_000_000


def _targets(args: argparse.Namespace, layer: AgentLayer) -> list[str]:
    if args.possessions:
        return args.possessions
    flagged = [p for p in layer.store.match_possessions(args.match) if p.flagged]
    return [p.id for p in sorted(flagged, key=lambda p: -p.severity)[: args.top]]


async def _generate(layer: AgentLayer, requests: list[NarrationRequest], concurrency: int) -> Counter:
    narrator, cache = layer.narratives.narrator, layer.narratives.cache
    outcomes: Counter = Counter()
    gate = asyncio.Semaphore(concurrency)

    async def one(request: NarrationRequest) -> None:
        async with gate:
            try:
                result = await narrator.generate(request)
            except Exception as error:  # report and carry on; nothing is cached for this one
                outcomes[f"error: {type(error).__name__}"] += 1
                return
            cache.put(request.cache_key(narrator.model), result.narrative)
            outcomes[result.narrative.status] += 1
            for rejection in result.rejections:
                outcomes[f"rejected: {rejection.code}"] += 1

    await asyncio.gather(*(one(r) for r in requests))
    return outcomes


def main() -> None:
    parser = argparse.ArgumentParser()
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--possessions", nargs="+")
    target.add_argument("--match")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--styles", nargs="+", default=list(presets_by_id(load_lens())))
    parser.add_argument("--audiences", nargs="+", default=list(get_args(Audience)))
    parser.add_argument("--languages", nargs="+", default=list(supported_languages()))
    parser.add_argument("--yes", action="store_true", help="make the calls (otherwise only report them)")
    args = parser.parse_args()

    settings = Settings()
    engine = settings.store == "engine"
    store = EngineStore.from_settings(settings) if engine else FixtureStore(settings.fixtures_dir)
    layer = AgentLayer.from_settings(settings, store)
    if layer.narratives.narrator is None:
        raise SystemExit("MISTRAL_API_KEY is not set")
    model = layer.narratives.model
    requests = [
        layer.narration(pid, style, audience, language)
        for pid in _targets(args, layer)
        for style in args.styles
        for audience in args.audiences
        for language in args.languages
    ]
    todo = [r for r in requests if layer.narratives.cache.get(r.cache_key(model), Narrative) is None]
    cached = len(requests) - len(todo)
    print(
        f"{len(requests)} narratives, {cached} already cached: {len(todo)} calls to {model}, "
        f"about ${len(todo) * COST_PER_CALL:.3f} (a rejected draft adds a second call)"
    )
    if not args.yes:
        print("Dry run. Add --yes to generate them.")
        return
    outcomes = asyncio.run(_generate(layer, todo, settings.narrator_concurrency))
    print(", ".join(f"{k}: {v}" for k, v in sorted(outcomes.items())) or "nothing to do")
    print(f"{layer.narratives.budget.used} tokens used")


if __name__ == "__main__":
    main()
