"""Export the static bundle for the web app's offline mode. Narratives come from the agent cache where a
verified one exists (fill it with scripts/prewarm_narratives.py), and are templates otherwise.

Usage: uv run python scripts/export_bundle.py [--store engine] [--matches a,b] [--public] [--out DIR]
  --store    fixtures (the default) or engine (analyses from the engine cache; needs DATA_DIR)
  --matches  match IDs to include, comma-separated (default: every match in the store)
  --public   leave out position tracks and coordinates (for anything published)
  --out      where to write it (default: web/public/bundle)
"""

import argparse
from pathlib import Path

from filmroom.agents.cache import JsonCache
from filmroom.agents.layer import AgentLayer
from filmroom.api.bundle import export_bundle
from filmroom.api.engine_store import EngineStore
from filmroom.api.store import FixtureStore
from filmroom.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", choices=["fixtures", "engine"], default="fixtures")
    parser.add_argument("--matches", type=lambda s: s.split(","), default=None)
    parser.add_argument("--public", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("web/public/bundle"))
    args = parser.parse_args()
    settings = Settings()
    store = (
        EngineStore.from_settings(settings) if args.store == "engine" else FixtureStore(settings.fixtures_dir)
    )
    cache = JsonCache(settings.cache_dir / "agents")
    agents = AgentLayer.offline(store, cache, settings.mistral_chat_model)
    manifest = export_bundle(store, args.out, public=args.public, agents=agents, match_ids=args.matches)
    print(f"wrote {len(manifest.files)} files to {args.out} (public={manifest.public})")


if __name__ == "__main__":
    main()
