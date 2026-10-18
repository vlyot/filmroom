"""Static bundle: every GET response the web app needs, written as files at paths that mirror the routes,
from any store (the fixtures, or engine output for chosen matches).

The offline web app reads the same JSON the API returns, so the two cannot drift. `public=True` leaves out
position tracks and option coordinates: there is no licence to redistribute SoccER-derived positions.
"""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

from fastapi.testclient import TestClient

from filmroom.agents.facts import supported_languages
from filmroom.agents.layer import AgentLayer
from filmroom.api.app import create_app
from filmroom.api.store import Store
from filmroom.contracts.models import CONTRACT_VERSION, Audience, BundleManifest
from filmroom.style import load_lens, presets_by_id


def route_to_path(route: str, params: dict[str, str | int] | None = None) -> str:
    """/possessions/x -> possessions/x.json; a query -> its values joined in the order given, e.g. a
    narrative's {style}.{audience}.{language}.json."""
    path = route.strip("/")
    if params:
        return f"{path}/{'.'.join(str(v) for v in params.values())}.json"
    return f"{path}.json"


def _strip_coordinates(possession: dict) -> dict:
    for decision in possession["decisions"]:
        for option in decision["options"]:
            option["target_xy"] = None
    return possession


Request = tuple[str, dict[str, str | int] | None]


def _match_requests(store: Store, match_id: str, public: bool) -> list[Request]:
    """Positions for every possession (the replay shows them all); the full possession and its narratives only
    for flagged ones, the only ones the app opens. Session packs and overlay for every preset."""
    styles = list(presets_by_id(load_lens()))
    audiences, languages = get_args(Audience), supported_languages()
    requests: list[Request] = [(f"/matches/{match_id}", None), (f"/matches/{match_id}/possessions", None)]
    requests += [(f"/matches/{match_id}/overlay", {"style": style}) for style in styles]
    requests += [
        (
            f"/matches/{match_id}/session-pack",
            {"team": team, "period": period, "style": style, "audience": audience, "language": language},
        )
        for team in (0, 1)
        for period in ("half", "full")
        for style in styles
        for audience in audiences
        for language in languages
    ]
    for possession in store.match_possessions(match_id):
        if not public:
            requests.append((f"/possessions/{possession.id}/positions", None))
        if not possession.flagged:
            continue
        requests.append((f"/possessions/{possession.id}", None))
        requests += [
            (f"/possessions/{possession.id}/narrative", {"style": s, "audience": a, "language": lang})
            for s in styles
            for a in audiences
            for lang in languages
        ]
    return requests


def export_bundle(
    store: Store,
    out_dir: Path,
    public: bool,
    agents: AgentLayer | None = None,
    match_ids: list[str] | None = None,
) -> BundleManifest:
    """Every match in the store, or only `match_ids`. Narratives come from the agent layer: the cached
    verified one where it has it, the template otherwise."""
    client = TestClient(create_app(store, cors_origins=[], agents=agents))
    matches = [m.id for m in store.matches() if match_ids is None or m.id in match_ids]
    if match_ids is not None and (unknown := set(match_ids) - set(matches)):
        raise KeyError(f"not in the store: {', '.join(sorted(unknown))}")
    requests: list[Request] = [("/matches", None), ("/styles", None), ("/styles/lens", None)]
    for match_id in matches:
        requests += _match_requests(store, match_id, public)

    if out_dir.exists():
        shutil.rmtree(out_dir)
    files = []
    for route, params in requests:
        response = client.get(route, params=params)
        response.raise_for_status()
        body = response.json()
        if route == "/matches":
            body = [m for m in body if m["id"] in matches]
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
