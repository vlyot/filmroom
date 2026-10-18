import os
import subprocess
import sys

import pytest

from tests.test_db_store import _seeded

PROBE = """
import sys
from filmroom.api.store import open_store
from filmroom.config import Settings
store = open_store(Settings(_env_file=None, store=sys.argv[1], database_url=sys.argv[2] or None))
engine = ("filmroom.engine.training", "filmroom.engine.analyse")
print(store.source, any(m.startswith(engine) for m in sys.modules))
"""


def _probe(store: str, url: str = "") -> str:
    result = subprocess.run(
        [sys.executable, "-c", PROBE, store, url], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def test_the_fixture_store_opens_without_the_engine():
    assert _probe("fixtures") == "fixtures False"


@pytest.mark.pg
def test_the_database_store_opens_without_the_engine(pg_pool):
    _seeded(pg_pool)
    assert _probe("database", os.environ["TEST_DATABASE_URL"]) == "database False"
