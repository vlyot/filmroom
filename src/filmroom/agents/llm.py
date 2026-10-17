"""LLM access. Every agent shares one Agent Framework chat client, and every model call it makes (each step of
a tool-calling loop included) passes through LlmBudget, which keeps calls under Mistral's request rate,
refuses once the day's tokens are spent, and logs the tokens each call used. The $10 monthly allowance is
the real limit, and `/narrative` and `/analyst` are public, so the daily cap keeps a burst of traffic from
spending it.

`make_chat_client` is the one place that names a provider; another Agent Framework client (Foundry, OpenAI)
slots in there.
"""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

import httpx
from agent_framework import ChatContext, ChatMiddleware, SupportsChatGetResponse
from agent_framework.mistral import MistralChatClient

from filmroom.config import Settings

log = logging.getLogger("filmroom.llm")
PURPOSE: ContextVar[str] = ContextVar("llm_purpose", default="other")
REQUESTS_PER_SECOND = 1.5  # Mistral Small 4 allows 1.67
REQUEST_TIMEOUT_S = 20  # one model call; the Mistral SDK would otherwise wait up to five minutes
TOOL_LOOP_LIMITS = {"max_iterations": 6, "max_function_calls": 8, "max_duration_seconds": 40.0}


class BudgetExhausted(Exception):
    """The day's token allowance is spent; callers fall back to templates or report the analyst offline."""


@contextmanager
def purpose(name: str) -> Iterator[None]:
    """Labels the model calls made inside the block in the usage log (narrator, analyst, themes)."""
    token = PURPOSE.set(name)
    try:
        yield
    finally:
        PURPOSE.reset(token)


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


class LlmBudget(ChatMiddleware):
    def __init__(
        self,
        daily_tokens: int,
        per_second: float = REQUESTS_PER_SECOND,
        clock: Callable[[], float] = time.monotonic,
        today: Callable[[], str] = _today,
    ):
        self.daily_tokens = daily_tokens
        self.interval = 1 / per_second
        self._clock = clock
        self._today = today
        self._day = today()
        self._used = 0
        self._next_slot = 0.0

    @property
    def used(self) -> int:
        if (day := self._today()) != self._day:
            self._day, self._used = day, 0
        return self._used

    @property
    def exhausted(self) -> bool:
        return self.used >= self.daily_tokens

    async def _wait_turn(self) -> None:
        now = self._clock()
        slot = max(now, self._next_slot)
        self._next_slot = slot + self.interval
        if slot > now:
            await asyncio.sleep(slot - now)

    async def process(self, context: ChatContext, call_next: Callable[[], Awaitable[None]]) -> None:
        if self.exhausted:
            raise BudgetExhausted(f"{self.used} of {self.daily_tokens} tokens used today")
        await self._wait_turn()
        start = time.perf_counter()
        outcome = "ok"
        try:
            await call_next()
        except BaseException as error:  # cancellations too, so a timed-out call isn't logged as ok
            outcome = type(error).__name__
            raise
        finally:
            usage = getattr(context.result, "usage_details", None) or {}
            tokens_in = usage.get("input_token_count") or 0
            tokens_out = usage.get("output_token_count") or 0
            self._used = self.used + tokens_in + tokens_out
            log.info(
                json.dumps(
                    {
                        "event": "llm_call",
                        "purpose": PURPOSE.get(),
                        "model": getattr(context.result, "model", None),
                        "tokens_in": tokens_in,
                        "tokens_out": tokens_out,
                        "latency_ms": round((time.perf_counter() - start) * 1000),
                        "outcome": outcome,
                        "tokens_today": self._used,
                    }
                )
            )


def make_chat_client(settings: Settings, budget: LlmBudget) -> SupportsChatGetResponse | None:
    if settings.mistral_api_key is None:
        return None
    return MistralChatClient(
        model=settings.mistral_chat_model,
        api_key=settings.mistral_api_key.get_secret_value(),
        middleware=[budget],
        function_invocation_configuration=TOOL_LOOP_LIMITS,
        http_client=httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT_S, connect=5.0)),
    )
