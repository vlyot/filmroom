"""Analyse every match with the engine and fill the API's analysis cache (gitignored, under .cache/engine).

Usage: uv run python scripts/analyse_matches.py
"""

from time import perf_counter

from filmroom.api.engine_store import EngineStore
from filmroom.config import Settings


def main() -> None:
    store = EngineStore.from_settings(Settings())
    for match in store.matches():
        start = perf_counter()
        possessions = store.possessions(match.id)
        flagged = sum(p.flagged for p in possessions)
        print(
            f"{match.id}: {len(possessions)} possessions, {flagged} flagged ({perf_counter() - start:.1f} s)"
        )


if __name__ == "__main__":
    main()
