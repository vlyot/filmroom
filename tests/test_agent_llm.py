import asyncio
import json
import logging
import time

import pytest
from agent_framework import Agent

from filmroom.agents.cache import JsonCache, cache_key
from filmroom.agents.llm import BudgetExhausted, LlmBudget, purpose
from filmroom.contracts.models import Claim
from tests.agent_fakes import ScriptedChatClient

TOKENS_PER_CALL = 340  # what ScriptedChatClient reports


def _run(budget: LlmBudget, calls: int) -> None:
    client = ScriptedChatClient(["ok"] * calls, middleware=[budget])
    agent = Agent(client=client)

    async def go():
        for _ in range(calls):
            await agent.run("hello")

    asyncio.run(go())


def test_spaces_model_calls_under_the_request_rate():
    budget = LlmBudget(daily_tokens=10_000, per_second=10)
    start = time.perf_counter()
    _run(budget, 3)
    assert time.perf_counter() - start >= 0.2


def test_refuses_once_the_days_tokens_are_spent_and_resets_the_next_day():
    day = ["2026-10-14"]
    budget = LlmBudget(daily_tokens=2 * TOKENS_PER_CALL, per_second=1000, today=lambda: day[0])
    _run(budget, 2)
    assert budget.used == 2 * TOKENS_PER_CALL and budget.exhausted
    with pytest.raises(BudgetExhausted):
        _run(budget, 1)
    day[0] = "2026-10-15"
    assert not budget.exhausted
    _run(budget, 1)
    assert budget.used == TOKENS_PER_CALL


def test_logs_one_line_per_call_with_purpose_and_tokens(caplog):
    budget = LlmBudget(daily_tokens=10_000, per_second=1000)
    with caplog.at_level(logging.INFO, logger="filmroom.llm"), purpose("narrator"):
        _run(budget, 1)
    line = json.loads(caplog.records[-1].getMessage())
    assert line | {"latency_ms": 0} == {
        "event": "llm_call",
        "purpose": "narrator",
        "model": "scripted",
        "tokens_in": 300,
        "tokens_out": 40,
        "latency_ms": 0,
        "outcome": "ok",
        "tokens_today": TOKENS_PER_CALL,
    }


def test_cache_round_trips_through_disk_and_keys_on_every_input(tmp_path):
    value = Claim(type="better_option", ref="d2.pass.1")
    key = cache_key({"facts": {"a": 1}, "version": 1})
    JsonCache(tmp_path).put(key, value)
    assert JsonCache(tmp_path).get(key, Claim) == value
    assert cache_key({"version": 1, "facts": {"a": 1}}) == key
    assert cache_key({"facts": {"a": 2}, "version": 1}) != key
    assert JsonCache(None).get(key, Claim) is None
