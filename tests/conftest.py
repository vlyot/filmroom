import os
from pathlib import Path

import pytest

from filmroom.config import Settings

REPO = Path(__file__).resolve().parent.parent
MINI_MATCH = "Match_2000_01_01_#001"
TEAM0_IDS = range(0, 11)
TEAM1_IDS = range(18, 29)
N_FRAMES = 30
MISSING = (5, 156)  # frame 5 has no row for pid 156


def _roster_lines() -> list[str]:
    lines = []
    for team, ids, prefix in ((0, TEAM0_IDS, "Alpha"), (1, TEAM1_IDS, "Beta")):
        for i, text_id in enumerate(ids):
            role = "goalkeeper" if i == 0 else "other"
            lines.append(
                f"playerName: {prefix}{text_id}\t\tplayer id:{text_id}\t\tteam id: {team}\t\trole: {role}"
            )
    return lines


EVENT_LINES = [
    "frame: 0\tBegin First Half",
    "frame: 2\tpossession player: 5\tpossession team: 0\toutermostOtherTeamPlayerID: 20\tteamID: 1",
    "frame: 3\tpossession player: 5\tpossession team: 0\toutermostOtherTeamPlayerID: 20\tteamID: 1",
    "frame: 3\tKickingTheBall \tby player: 5\tteam: 0",
    "DEBUG - startedPassInCrossPosition = false\tside = -1\tx = 55.0\ty = 36.2",
    "frame: 3\tstarted shortPass \tby player: 5",
    "frame: 6\tframe start: 3\tcomplete pass\tby playerId: 5\tto playerID: 7\tteamId: 0",
    "frame: 6\tlast opponent position: 82.3\tlastPlayerID: 20\tlastTeamID: 1",
    "frame: 7\tpossession player: 23\tpossession team: 1\toutermostOtherTeamPlayerID: 2\tteamID: 0",
    "frame: 7\tstarted longPass \tby player: 23",
    "frame: 9\tframe start: 7\tfilteringPass\tby playerId: 23\tto playerID: 28\tteamId: 1",
    "frame: 10\tframe start: 8\tcross\tby playerId: 9\tto playerID: 5\tteamId: 0\toutcome: fallito",
    "frame: 12\tframe start: 11\tcomplete shot (no goal)\tby playerId: 9\tteamId: 0",
    "frame: 12\tframe start: 11\tcomplete shot (no goal)\tby playerId: 9\tteamId: 0",
    "frame: 12\tframe start: 11\tsaved shot\tof player: 9\tteamID: 0\tby goalkeeper: 18\tteamId: 1\tcase: X",
    "frame: 14\tframe start: 13\tcomplete shot (no goal)\tby playerId: 24\tteamId: 1",
    "frame: 16\tframe start: 15\tevent: shotThenGoal\t teamID: 0\tplayerID: 8",
    "frame: 16\tframe start: 14\tevent: passThenGoal\tsenderID: 10\tteamID: 0\tscorerID: 8\tteamID: 0",
    "frame: 17\tevent: goal\t teamID: 0\tplayerID: 8",
    "frame: 18\tAtomicTackle\tvictim player id: 7\tteam id: 0\ttackler player id: 23\tteam id: 1",
    "frame: 18\tstarted tackle A\tvictim player id: 7\ttackler player id: 23",
    "frame: 19\ttackle\tframe start: 18\tvictim player id: 7\tof team: 0\ttackler player id: 23\tof team: 1"
    "\toutcome: lose",
    "frame: 20\tBallOut - sideline",
    "frame: 21\tfoul:\tpenalty\tdue to player: 3\tteam id: 0",
    "foul type: yellow card \tto player: 3",
    "frame: 22\tdeflection \tby player: 18\tteam id: 1",
    "frame: 23\tmystery event\tfoo",
    "ZZZZ",
]


def write_mini_match(root: Path, match_id: str = MINI_MATCH) -> Path:
    match_dir = root / match_id
    match_dir.mkdir(parents=True)
    pids = [128, *(128 + i for i in TEAM1_IDS), *TEAM0_IDS]  # deliberately not in canonical order
    rows = []
    for frame in range(1, N_FRAMES + 1):
        for pid in pids:
            if (frame, pid) == MISSING:
                continue
            rows.append(f"{frame} {pid} {frame + pid / 1000:.6f} {pid % 72:.6f}")
    (match_dir / "positions.log").write_text("\n".join(rows) + "\n")
    times = ["frame,game_ms", *(f"{f},{52 + 10 * (f - 1)}" for f in range(1, N_FRAMES + 1))]
    (match_dir / "frame_times.csv").write_text("\n".join(times) + "\n")
    text = "\n".join(_roster_lines() + EVENT_LINES) + "\n"
    (match_dir / "Textual annotation.txt").write_text(text, encoding="utf-8")
    (match_dir / "Recording.MKV").write_bytes(b"")
    return match_dir


@pytest.fixture
def mini_root(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    write_mini_match(root)
    return root


@pytest.fixture
def mini_settings(mini_root: Path, tmp_path: Path) -> Settings:
    return Settings(_env_file=None, data_dir=mini_root, cache_dir=tmp_path / "cache")


@pytest.fixture
def mini_fixtures(mini_settings: Settings, tmp_path: Path) -> Path:
    """A fixture set built from the synthetic mini match, so API and bundle tests run without real data."""
    from filmroom.data.catalog import Catalog
    from filmroom.engine.assemble import match_view
    from filmroom.eval.labels import LabelRecord
    from filmroom.fixtures import FixtureSpec, build_possession, write_fixtures
    from filmroom.style import load_lens, presets

    spec = FixtureSpec.model_validate_json((REPO / "fixtures" / "fixture_spec.json").read_bytes())
    styles = presets(load_lens())
    md = Catalog(mini_settings).load(MINI_MATCH)
    label = LabelRecord("T01", "tuning", MINI_MATCH, 1, 20, None, 11, 9, 7, True, 3)
    fixture = build_possession(label, md, spec.possessions[0], spec.routine, styles)
    out = tmp_path / "fixtures"
    write_fixtures(out, [match_view(md)], [fixture])
    return out


@pytest.fixture(scope="session")
def real_settings() -> Settings:
    return Settings()


@pytest.fixture
def pg_pool():
    """A pool on TEST_DATABASE_URL with an empty schema, for tests marked `pg`."""
    import psycopg
    from psycopg_pool import ConnectionPool

    from filmroom.db.schema import ensure_schema

    url = os.environ["TEST_DATABASE_URL"]
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("drop schema if exists public cascade")
        conn.execute("create schema public")
        ensure_schema(conn)
    pool = ConnectionPool(url, min_size=1, max_size=2, open=True)
    yield pool
    pool.close()


def pytest_collection_modifyitems(config, items):
    data_dir = Settings().data_dir
    skips = {}
    if data_dir is None or not data_dir.is_dir():
        skips["data"] = pytest.mark.skip(reason="DATA_DIR not available")
    if os.environ.get("RUN_LLM_TESTS") != "1" or Settings().mistral_api_key is None:
        skips["llm"] = pytest.mark.skip(reason="spends Mistral allowance; set RUN_LLM_TESTS=1 to run")
    if not os.environ.get("TEST_DATABASE_URL"):
        skips["pg"] = pytest.mark.skip(reason="TEST_DATABASE_URL not set")
    for item in items:
        for marker, skip in skips.items():
            if marker in item.keywords:
                item.add_marker(skip)
