import pytest

from filmroom.agents.cache import JsonCache
from filmroom.contracts.models import Claim
from filmroom.db.cache import DbCache
from filmroom.db.seed import upload_cache

pytestmark = pytest.mark.pg

CLAIM = Claim(type="better_option", ref="d2.pass.1")
OTHER = Claim(type="better_option", ref="d3.shot.0")


def test_a_value_put_is_served_by_a_new_cache_after_a_restart(pg_pool):
    DbCache(pg_pool).put("k1", CLAIM)
    assert DbCache(pg_pool).get("k1", Claim) == CLAIM
    assert DbCache(pg_pool).get("missing", Claim) is None


def test_upload_adds_missing_entries_and_never_overwrites(pg_pool, tmp_path):
    DbCache(pg_pool).put("aa11", CLAIM)
    local = JsonCache(tmp_path)
    local.put("aa11", OTHER)
    local.put("bb22", OTHER)
    with pg_pool.connection() as conn:
        assert upload_cache(conn, tmp_path) == 1
        assert upload_cache(conn, tmp_path) == 0
    cache = DbCache(pg_pool)
    assert (cache.get("aa11", Claim), cache.get("bb22", Claim)) == (CLAIM, OTHER)
