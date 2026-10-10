"""Export the static bundle for the web app's offline mode.

Usage: uv run python scripts/export_bundle.py [--public] [--out web/public/bundle]
  --public  leave out position tracks and coordinates (for anything published)
"""

import argparse
from pathlib import Path

from filmroom.api.bundle import export_bundle
from filmroom.api.store import FixtureStore
from filmroom.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("web/public/bundle"))
    args = parser.parse_args()
    manifest = export_bundle(FixtureStore(Settings().fixtures_dir), args.out, public=args.public)
    print(f"wrote {len(manifest.files)} files to {args.out} (public={manifest.public})")


if __name__ == "__main__":
    main()
