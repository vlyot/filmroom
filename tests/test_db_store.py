import pytest
from fastapi.testclient import TestClient

from filmroom.api.app import create_app
from filmroom.api.bundle import export_bundle
from filmroom.api.db_store import DatabaseStore
from filmroom.contracts.models import CONTRACT_VERSION, Match
from filmroom.db.cache import DbCache
from filmroom.db.seed import seed
from filmroom.db.usage import UsageLedger
from tests.test_engine_store_api import SLUG, _store

pytestmark = pytest.mark.pg


def _seeded(pool, public=False, source=None) -> DatabaseStore:
    source = source or _store()
    with pool.connection() as conn:
        seed(conn, source, [m.id for m in source.matches()], public)
    return DatabaseStore(pool)


def _routes(store) -> list[str]:
    possessions = store.match_possessions(SLUG)
    flagged = next(p for p in possessions if p.flagged)
    routes = ["/matches", f"/matches/{SLUG}", f"/matches/{SLUG}/possessions", f"/matches/{SLUG}/overlay"]
    routes += [f"/possessions/{p.id}" for p in possessions]
    routes += [f"/possessions/{p.id}/positions" for p in possessions]
    routes += [
        f"/possessions/{flagged.id}/narrative?style=counter-low-block&audience=fan&language=es",
        f"/matches/{SLUG}/session-pack?team=0",
    ]
    return routes


def test_serves_every_route_as_the_engine_store_does(pg_pool):
    engine = _store()
    database = _seeded(pg_pool)
    expected, served = TestClient(create_app(engine, [])), TestClient(create_app(database, []))
    for route in _routes(engine):
        assert served.get(route).json() == expected.get(route).json(), route
    assert served.get("/health").json()["source"] == "database"


def test_exports_the_same_bundle_as_the_engine_store(pg_pool, tmp_path):
    export_bundle(_store(), tmp_path / "engine", public=False)
    export_bundle(_seeded(pg_pool), tmp_path / "database", public=False)
    files = {
        root: sorted(p.relative_to(tmp_path / root) for p in (tmp_path / root).rglob("*.json"))
        for root in ("engine", "database")
    }
    assert files["database"] == files["engine"]
    for rel in files["engine"]:
        if rel.name != "manifest.json":
            assert (tmp_path / "database" / rel).read_text() == (tmp_path / "engine" / rel).read_text(), rel


def test_a_public_seed_has_no_positions_or_option_coordinates(pg_pool):
    client = TestClient(create_app(_seeded(pg_pool, public=True), []))
    for summary in client.get(f"/matches/{SLUG}/possessions").json():
        assert client.get(f"/possessions/{summary['id']}/positions").status_code == 404
        possession = client.get(f"/possessions/{summary['id']}").json()
        assert {o["target_xy"] for d in possession["decisions"] for o in d["options"]} == {None}


def test_unknown_matches_and_possessions_are_404(pg_pool):
    client = TestClient(create_app(_seeded(pg_pool), []))
    missing = ["/matches/nope", "/matches/nope/possessions", "/possessions/nope", "/possessions/x/positions"]
    for route in missing:
        assert client.get(route).status_code == 404, route


def test_refuses_a_database_seeded_under_another_contract(pg_pool):
    with pytest.raises(RuntimeError, match="reseed"):
        DatabaseStore(pg_pool)
    _seeded(pg_pool)
    with pg_pool.connection() as conn:
        conn.execute("update meta set value = '0.0.1' where key = 'contract_version'")
    with pytest.raises(RuntimeError, match=f"contract {CONTRACT_VERSION}"):
        DatabaseStore(pg_pool)


def test_similar_situations_match_brute_force(pg_pool):
    engine, database = _store(), _seeded(pg_pool)
    for p in (p for p in engine.match_possessions(SLUG) if p.flagged):
        for style_id in p.verdicts:
            for all_matches in (False, True):
                expected = engine.similar(p.id, style_id, 5, all_matches)
                found = database.similar(p.id, style_id, 5, all_matches)
                assert [q.id for q, _ in found] == [q.id for q, _ in expected]
                assert [s for _, s in found] == pytest.approx([s for _, s in expected], abs=2e-4)


def test_reseeding_keeps_the_narrative_cache_and_the_ledger(pg_pool):
    match = _seeded(pg_pool).match(SLUG)
    DbCache(pg_pool).put("k", match)
    UsageLedger(pg_pool).add("2026-10-18", "narrator", 900, 100)
    _seeded(pg_pool)
    assert DbCache(pg_pool).get("k", Match) == match
    assert UsageLedger(pg_pool).day_total("2026-10-18") == 1000


class _Breaks:
    """A store whose positions fail halfway through a seed."""

    def __init__(self, store):
        self.store = store

    def __getattr__(self, name):
        return getattr(self.store, name)

    def positions(self, possession_id):
        raise OSError("disk gone")


def test_a_failed_seed_leaves_the_previous_data_serving(pg_pool):
    _seeded(pg_pool)
    with pytest.raises(OSError):
        _seeded(pg_pool, source=_Breaks(_store()))
    store, engine = DatabaseStore(pg_pool), _store()
    assert [m.id for m in store.matches()] == [SLUG]
    first = engine.match_possessions(SLUG)[0].id
    assert store.positions(first) == engine.positions(first)
