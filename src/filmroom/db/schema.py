"""The schema. Matches, possessions, positions and situation vectors are derived from engine output and
replaced whole by every seed; the narrative cache and the token ledger hold what was paid for and survive
reseeds.
Bodies are stored as the contract's JSON text and validated on the way out, as the file stores do.

SCHEMA_VERSION covers the derived tables: a store refuses a database seeded under another version. The two
lasting tables are created if missing and never altered here.
"""

from functools import cache

from psycopg import Connection
from psycopg_pool import ConnectionPool

from filmroom.agents.situations import SITUATION_DIM

SCHEMA_VERSION = 1

DDL = f"""
create extension if not exists vector;
create table if not exists meta (key text primary key, value text not null);
create table if not exists matches (
    id text primary key,
    ord integer not null,
    summary text not null,
    body text not null
);
create table if not exists possessions (
    id text primary key,
    match_id text not null references matches (id) on delete cascade,
    ord integer not null,
    summary text not null,
    body text not null
);
create index if not exists possessions_by_match on possessions (match_id, ord);
create table if not exists positions (
    possession_id text primary key references possessions (id) on delete cascade,
    body text not null
);
create table if not exists situations (
    style_id text not null,
    possession_id text not null references possessions (id) on delete cascade,
    match_id text not null,
    flagged boolean not null,
    embedding vector({SITUATION_DIM}) not null,
    primary key (style_id, possession_id)
);
create table if not exists narrative_cache (
    key text primary key,
    body text not null,
    created_at timestamptz not null default now()
);
create table if not exists llm_usage (
    day date not null,
    purpose text not null,
    calls integer not null default 0,
    tokens_in bigint not null default 0,
    tokens_out bigint not null default 0,
    primary key (day, purpose)
);
"""


def ensure_schema(conn: Connection) -> None:
    conn.execute(DDL)


def read_meta(conn: Connection) -> dict[str, str]:
    return dict(conn.execute("select key, value from meta").fetchall())


@cache
def open_pool(url: str) -> ConnectionPool:
    """One pool per database for the whole process, shared by the store, the cache and the ledger, with the
    schema in place."""
    pool = ConnectionPool(url, min_size=1, max_size=4, open=True)
    with pool.connection() as conn:
        ensure_schema(conn)
    return pool
