"""Database-backed store: serves engine output seeded into Postgres (filmroom.db.seed), so the deployed API
needs neither the dataset nor the engine's models, and holds only the few matches being replayed in memory.
"Similar situations" is a pgvector cosine search over the seeded situation vectors."""

from functools import lru_cache

from psycopg_pool import ConnectionPool

from filmroom.config import Settings
from filmroom.contracts.models import (
    CONTRACT_VERSION,
    Match,
    MatchSummary,
    PositionsChunk,
    Possession,
    PossessionSummary,
)
from filmroom.db.schema import SCHEMA_VERSION, open_pool, read_meta

MATCHES_IN_MEMORY = 4

SIMILAR = """
with target as (
    select embedding from situations where style_id = %(style)s and possession_id = %(id)s
)
select p.body, 1 - (s.embedding <=> target.embedding)
from situations s
join possessions p on p.id = s.possession_id
join matches m on m.id = s.match_id
cross join target
where s.style_id = %(style)s and s.flagged and s.possession_id <> %(id)s
    and (%(all)s or s.match_id = %(match)s)
order by s.embedding <=> target.embedding, m.ord, p.ord
limit %(k)s
"""


class DatabaseStore:
    source = "database"

    def __init__(self, pool: ConnectionPool):
        self._pool = pool
        with pool.connection() as conn:
            meta = read_meta(conn)
        seeded = (meta.get("schema_version"), meta.get("contract_version"))
        if seeded != (str(SCHEMA_VERSION), CONTRACT_VERSION):
            raise RuntimeError(
                f"database seeded under schema {seeded[0]}, contract {seeded[1]}; this build needs schema "
                f"{SCHEMA_VERSION}, contract {CONTRACT_VERSION}: reseed with scripts/seed_db.py"
            )
        self.match_possessions = lru_cache(maxsize=MATCHES_IN_MEMORY)(self._match_possessions)

    @classmethod
    def from_settings(cls, settings: Settings) -> "DatabaseStore":
        if settings.database_url is None:
            raise ValueError("STORE=database needs DATABASE_URL")
        return cls(open_pool(settings.database_url.get_secret_value()))

    def _one(self, query: str, key: str) -> str:
        with self._pool.connection() as conn:
            row = conn.execute(query, (key,)).fetchone()
        if row is None:
            raise KeyError(f"not found: {key}")
        return row[0]

    def _rows(self, match_id: str, column: str) -> list[str]:
        self._one("select id from matches where id = %s", match_id)
        with self._pool.connection() as conn:
            query = f"select {column} from possessions where match_id = %s order by ord"
            return [r[0] for r in conn.execute(query, (match_id,))]

    def matches(self) -> list[MatchSummary]:
        with self._pool.connection() as conn:
            rows = conn.execute("select summary from matches order by ord").fetchall()
        return [MatchSummary.model_validate_json(r[0]) for r in rows]

    def match(self, match_id: str) -> Match:
        return Match.model_validate_json(self._one("select body from matches where id = %s", match_id))

    def possessions(self, match_id: str) -> list[PossessionSummary]:
        return [PossessionSummary.model_validate_json(s) for s in self._rows(match_id, "summary")]

    def _match_possessions(self, match_id: str) -> list[Possession]:
        return [Possession.model_validate_json(b) for b in self._rows(match_id, "body")]

    def possession(self, possession_id: str) -> Possession:
        return Possession.model_validate_json(
            self._one("select body from possessions where id = %s", possession_id)
        )

    def positions(self, possession_id: str) -> PositionsChunk:
        return PositionsChunk.model_validate_json(
            self._one("select body from positions where possession_id = %s", possession_id)
        )

    def similar(
        self, possession_id: str, style_id: str, k: int, all_matches: bool
    ) -> list[tuple[Possession, float]]:
        match_id = self._one("select match_id from situations where possession_id = %s", possession_id)
        params = {"style": style_id, "id": possession_id, "all": all_matches, "match": match_id, "k": k}
        with self._pool.connection() as conn:
            rows = conn.execute(SIMILAR, params).fetchall()
        return [(Possession.model_validate_json(body), round(float(sim), 4)) for body, sim in rows]
