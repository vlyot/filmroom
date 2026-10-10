"""Static bundle: every GET response the web app needs, written as files at paths that mirror the routes.

The offline web app reads the same JSON the API returns, so the two cannot drift. `public=True` leaves out
position tracks and option coordinates: there is no licence to redistribute SoccER-derived positions.
"""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from filmroom.api.app import create_app
from filmroom.api.store import FixtureStore
from filmroom.contracts.models import CONTRACT_VERSION, BundleManifest


def route_to_path(route: str, params: dict[str, str] | None = None) -> str:
    """/possessions/x -> possessions/x.json; a narrative query -> {style}.{audience}.{language}.json."""
    path = route.strip("/")
    if params:
        return f"{path}/{params['style']}.{params['audience']}.{params['language']}.json"
    return f"{path}.json"


def _strip_coordinates(possession: dict) -> dict:
    for decision in possession["decisions"]:
        for option in decision["options"]:
            option["target_xy"] = None
    return possession


def export_bundle(store: FixtureStore, out_dir: Path, public: bool) -> BundleManifest:
    client = TestClient(create_app(store, cors_origins=[]))
    requests: list[tuple[str, dict[str, str] | None]] = [("/matches", None), ("/styles", None)]
    for match in store.matches():
        requests += [(f"/matches/{match.id}", None), (f"/matches/{match.id}/possessions", None)]
    for fixture in store.all_fixtures():
        pid = fixture.possession.id
        requests.append((f"/possessions/{pid}", None))
        if not public:
            requests.append((f"/possessions/{pid}/positions", None))
        for n in fixture.narratives:
            params = {"style": n.style_id, "audience": n.audience, "language": n.language}
            requests.append((f"/possessions/{pid}/narrative", params))

    if out_dir.exists():
        shutil.rmtree(out_dir)
    files = []
    for route, params in requests:
        response = client.get(route, params=params)
        response.raise_for_status()
        body = response.json()
        if public and route.startswith("/possessions/") and route.count("/") == 2:
            body = _strip_coordinates(body)
        rel = route_to_path(route, params)
        target = out_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        files.append(rel)

    manifest = BundleManifest(
        contract_version=CONTRACT_VERSION,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        public=public,
        files=sorted(files),
    )
    (out_dir / "manifest.json").write_text(manifest.model_dump_json(indent=1), encoding="utf-8")
    return manifest
