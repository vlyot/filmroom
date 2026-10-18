"""Seeding: copies a store's engine output for chosen matches into Postgres, then the local narrative cache.
It runs on a machine with the dataset (scripts/seed_db.py); the deployed API serves only what it wrote."""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from psycopg import Connection

from filmroom.agents.situations import situation_vector
from filmroom.api.store import Store, strip_coordinates, summary_of
from filmroom.contracts.models import CONTRACT_VERSION, MatchSummary, Possession
from filmroom.db.schema import SCHEMA_VERSION, ensure_schema


@dataclass
class SeedCounts:
    matches: int = 0
    possessions: int = 0
    positions: int = 0
    situations: int = 0


def vector_literal(values: Iterable[float]) -> str:
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def _body(possession: Possession, public: bool) -> str:
    if public:
        return json.dumps(strip_coordinates(possession.model_dump(mode="json")), ensure_ascii=False)
    return possession.model_dump_json()


def seed(conn: Connection, source: Store, match_ids: list[str], public: bool) -> SeedCounts:
    """Replaces every derived table with the source's output for `match_ids`, in that order, in one
    transaction, so a seed that fails leaves the previous data serving. With `public`, no positions and no
    option coordinates, as in the public bundle. Situation vectors are stored under every style a possession
    has a verdict for. The narrative cache and the token ledger are left alone."""
    counts = SeedCounts()
    with conn.transaction(), conn.cursor() as cur:
        ensure_schema(conn)
        cur.execute("truncate matches, possessions, positions, situations")
        for ord_, match_id in enumerate(match_ids):
            match = source.match(match_id)
            summary = MatchSummary.model_validate(match.model_dump(exclude={"players"}))
            cur.execute(
                "insert into matches values (%s, %s, %s, %s)",
                (match.id, ord_, summary.model_dump_json(), match.model_dump_json()),
            )
            possessions = source.match_possessions(match_id)
            cur.executemany(
                "insert into possessions values (%s, %s, %s, %s, %s)",
                [
                    (p.id, match.id, i, summary_of(p).model_dump_json(), _body(p, public))
                    for i, p in enumerate(possessions)
                ],
            )
            if not public:
                cur.executemany(
                    "insert into positions values (%s, %s)",
                    [(p.id, source.positions(p.id).model_dump_json()) for p in possessions],
                )
                counts.positions += len(possessions)
            situations = [
                (style_id, p.id, match.id, p.flagged, vector_literal(situation_vector(p, style_id)))
                for p in possessions
                for style_id in p.verdicts
            ]
            cur.executemany("insert into situations values (%s, %s, %s, %s, %s::vector)", situations)
            counts.matches += 1
            counts.possessions += len(possessions)
            counts.situations += len(situations)
        meta = {
            "schema_version": str(SCHEMA_VERSION),
            "contract_version": CONTRACT_VERSION,
            "public": json.dumps(public),
            "matches": ",".join(match_ids),
            "seeded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        cur.executemany(
            "insert into meta values (%s, %s) on conflict (key) do update set value = excluded.value",
            list(meta.items()),
        )
    return counts


def upload_cache(conn: Connection, cache_dir: Path) -> int:
    """Adds the local cache's entries (CACHE_DIR/agents: narratives and themes) that the database lacks, and
    returns how many. It never overwrites, so what the API already serves stays as it is."""
    rows = [(path.stem, path.read_text(encoding="utf-8")) for path in sorted(cache_dir.glob("*/*.json"))]
    with conn.transaction(), conn.cursor() as cur:
        before = cur.execute("select count(*) from narrative_cache").fetchone()[0]
        cur.executemany(
            "insert into narrative_cache (key, body) values (%s, %s) on conflict (key) do nothing", rows
        )
        return cur.execute("select count(*) from narrative_cache").fetchone()[0] - before
