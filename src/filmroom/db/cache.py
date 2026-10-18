"""The agent cache in Postgres, so a redeploy keeps every narrative and theme already paid for.

Every row is read once at start-up and `get` answers from memory: the narrative service calls it on the event
loop, many times per request for views that list moments. `put` writes through. That is only right with a
single API replica, which is how the deployed API runs.
"""

from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from filmroom.config import Settings
from filmroom.db.schema import open_pool


class DbCache:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool
        with pool.connection() as conn:
            self._memory: dict[str, str] = dict(conn.execute("select key, body from narrative_cache"))

    @classmethod
    def from_settings(cls, settings: Settings) -> "DbCache":
        return cls(open_pool(settings.database_url.get_secret_value()))

    def get[M: BaseModel](self, key: str, model: type[M]) -> M | None:
        body = self._memory.get(key)
        return model.model_validate_json(body) if body is not None else None

    def put(self, key: str, value: BaseModel) -> None:
        self._memory[key] = value.model_dump_json()
        with self._pool.connection() as conn:
            conn.execute(
                "insert into narrative_cache (key, body) values (%s, %s) "
                "on conflict (key) do update set body = excluded.body",
                (key, self._memory[key]),
            )
