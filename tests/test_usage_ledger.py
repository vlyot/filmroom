import pytest

from filmroom.agents.llm import LlmBudget, purpose
from filmroom.db.usage import PurposeUsage, UsageLedger
from tests.test_agent_llm import TOKENS_PER_CALL, _run

pytestmark = pytest.mark.pg


def test_the_budget_records_calls_and_restores_the_day_after_a_restart(pg_pool):
    ledger, day = UsageLedger(pg_pool), "2026-10-18"
    budget = LlmBudget(daily_tokens=10_000, per_second=1000, today=lambda: day, ledger=ledger)
    with purpose("narrator"):
        _run(budget, 2)
    restarted = LlmBudget(daily_tokens=10_000, per_second=1000, today=lambda: day, ledger=ledger)
    assert restarted.used == budget.used == 2 * TOKENS_PER_CALL
    assert LlmBudget(daily_tokens=10_000, today=lambda: "2026-10-19", ledger=ledger).used == 0


def test_month_sums_calls_and_tokens_by_purpose_within_the_month(pg_pool):
    ledger = UsageLedger(pg_pool)
    ledger.add("2026-09-30", "narrator", 5000, 500)
    ledger.add("2026-10-01", "narrator", 900, 100)
    ledger.add("2026-10-18", "narrator", 1000, 120)
    ledger.add("2026-10-18", "analyst", 3000, 200)
    ledger.add("2026-10-19", "analyst", 7000, 700)
    assert ledger.month("2026-10-18") == [
        PurposeUsage("analyst", 1, 3000, 200),
        PurposeUsage("narrator", 2, 1900, 220),
    ]
