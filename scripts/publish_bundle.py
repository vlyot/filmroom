"""Publish the static bundle that GitHub Pages serves when the API is down.

CI has no SoccER data, so the bundle is exported here: from the engine store, with verified narratives from
the agent cache (DATABASE_URL set: the deployed API's cache). It is packed as bundle.tar.gz on the GitHub
release "bundle", replacing the previous one, and the Pages workflow is started; that workflow refuses a
bundle exported under another contract version. Without --yes it only exports and reports.

Usage: uv run python scripts/publish_bundle.py --matches a,b [--public] [--yes]
"""

import argparse
import subprocess
import tarfile
import tempfile
from pathlib import Path

from filmroom.agents.cache import open_cache
from filmroom.agents.layer import AgentLayer
from filmroom.api.bundle import export_bundle
from filmroom.api.store import open_store
from filmroom.config import Settings

RELEASE = "bundle"
ASSET = "bundle.tar.gz"


def _gh(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], check=check, capture_output=True, text=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matches", type=lambda s: s.split(","), required=True)
    parser.add_argument("--public", action="store_true")
    parser.add_argument("--yes", action="store_true", help="upload and deploy (otherwise only export)")
    args = parser.parse_args()

    settings = Settings(store="engine")
    store = open_store(settings)
    agents = AgentLayer.offline(store, open_cache(settings), settings.mistral_chat_model)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "bundle"
        manifest = export_bundle(store, out, public=args.public, agents=agents, match_ids=args.matches)
        archive = Path(tmp) / ASSET
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(out, arcname=".")
        size_mb = archive.stat().st_size / 1e6
        print(
            f"bundle: {len(manifest.files)} files, {size_mb:.1f} MB packed, contract "
            f"{manifest.contract_version}, public={manifest.public}"
        )
        if not args.yes:
            print("Dry run. Add --yes to upload it and deploy GitHub Pages.")
            return
        if _gh("release", "view", RELEASE, check=False).returncode != 0:
            notes = "The static bundle GitHub Pages serves offline. Replaced by scripts/publish_bundle.py."
            _gh("release", "create", RELEASE, "--title", "Static bundle", "--notes", notes, "--latest=false")
        _gh("release", "upload", RELEASE, str(archive), "--clobber")
    _gh("workflow", "run", "pages.yml", "--ref", "main")
    print(f"uploaded {ASSET} to the {RELEASE} release and started the Pages deploy")


if __name__ == "__main__":
    main()
