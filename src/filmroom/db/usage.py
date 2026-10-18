"""The LLM token ledger: calls and tokens per UTC day and purpose, so the daily cap survives a restart and the
month's use can be read against Mistral's included allowance."""

from dataclasses import dataclass

from psycopg_pool import ConnectionPool


@dataclass(frozen=True)
class PurposeUsage:
    purpose: str
    calls: int
    tokens_in: int
    tokens_out: int


class UsageLedger:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    def add(self, day: str, purpose: str, tokens_in: int, tokens_out: int) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "insert into llm_usage values (%s, %s, 1, %s, %s) on conflict (day, purpose) do update set "
                "calls = llm_usage.calls + 1, tokens_in = llm_usage.tokens_in + excluded.tokens_in, "
                "tokens_out = llm_usage.tokens_out + excluded.tokens_out",
                (day, purpose, tokens_in, tokens_out),
            )

    def day_total(self, day: str) -> int:
        with self._pool.connection() as conn:
            row = conn.execute(
                "select coalesce(sum(tokens_in + tokens_out), 0) from llm_usage where day = %s", (day,)
            ).fetchone()
        return int(row[0])

    def month(self, day: str) -> list[PurposeUsage]:
        """Use from the first of `day`'s month up to and including `day`, by purpose."""
        with self._pool.connection() as conn:
            rows = conn.execute(
                "select purpose, sum(calls), sum(tokens_in), sum(tokens_out) from llm_usage "
                "where day between date_trunc('month', %s::date) and %s::date "
                "group by purpose order by purpose",
                (day, day),
            ).fetchall()
        return [PurposeUsage(p, int(c), int(i), int(o)) for p, c, i, o in rows]
