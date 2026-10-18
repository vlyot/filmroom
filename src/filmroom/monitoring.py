"""The API's own counters, served at /metrics. The agents already log one JSON line per model call, narrative
and analyst reply (Railway keeps those lines); a logging handler counts the same events, so nothing is
reported twice by hand. Requests and replay sockets are counted where they are served.

Counters start at zero with each process. The day's tokens come from the LLM budget, and the month's from the
token ledger, which survives restarts.
"""

import json
import logging
import math
import time
from collections import Counter, deque
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from fastapi import Request, Response
from starlette.middleware.base import RequestResponseEndpoint

from filmroom.agents.llm import MONTHLY_ALLOWANCE_USD, LlmBudget, estimated_cost
from filmroom.contracts.models import (
    CONTRACT_VERSION,
    Latency,
    LlmMetrics,
    MetricsReport,
    OutcomeMetrics,
    RequestMetrics,
    StoreSource,
)

log = logging.getLogger("filmroom.requests")
SAMPLES = 500
SLOW_MS = 1000


def _latency(samples: deque[float]) -> Latency:
    def at(q: float) -> float | None:
        if not samples:
            return None
        ordered = sorted(samples)
        return round(ordered[max(0, math.ceil(q * len(ordered)) - 1)], 1)

    return Latency(p50_ms=at(0.5), p95_ms=at(0.95))


def _outcomes(verified: int, fallback: int, rejected: int, drafted: int) -> OutcomeMetrics:
    total = verified + fallback
    return OutcomeMetrics(
        verified=verified,
        fallback=fallback,
        rejected=rejected,
        fallback_rate=round(fallback / total, 3) if total else None,
        rejection_rate=round(rejected / drafted, 3) if drafted else None,
    )


class Metrics:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._started = clock()
        self.counts: Counter[str] = Counter()
        self._request_ms: deque[float] = deque(maxlen=SAMPLES)
        self._llm_ms: deque[float] = deque(maxlen=SAMPLES)
        self.replays_active = 0

    def observe(self, event: dict) -> None:
        """One of the agents' JSON log events; others are ignored."""
        match event.get("event"):
            case "llm_call":
                self.counts["llm_calls"] += 1
                self.counts["llm_errors"] += event.get("outcome") != "ok"
                self._llm_ms.append(event.get("latency_ms", 0))
            case "narrative":
                self.counts[
                    "narratives_verified" if event.get("status") == "verified" else "narratives_failed"
                ] += 1
                self.counts["narratives_rejected"] += bool(event.get("rejections"))
            case "narrative_error":
                self.counts["narratives_error"] += 1
            case "analyst":
                self.counts["analyst_verified"] += 1
                self.counts["analyst_rejected"] += bool(event.get("retried"))
            case "analyst_fallback":
                self.counts["analyst_fallback"] += 1
                self.counts["analyst_rejected"] += 1
            case "analyst_error":
                self.counts["analyst_error"] += 1

    def request(self, method: str, route: str, status: int, ms: float) -> None:
        self.counts["requests"] += 1
        self.counts["request_errors"] += status >= 500
        self._request_ms.append(ms)
        if status >= 500 or ms > SLOW_MS:
            record = {"event": "request", "method": method, "route": route, "status": status, "ms": round(ms)}
            log.log(logging.WARNING if status >= 500 else logging.INFO, json.dumps(record))

    @contextmanager
    def replay(self) -> Iterator[None]:
        self.replays_active += 1
        self.counts["replays"] += 1
        try:
            yield
        finally:
            self.replays_active -= 1

    @contextmanager
    def listening(self) -> Iterator[None]:
        """Counts the agents' log events while the block runs (the app's lifespan)."""
        logger = logging.getLogger("filmroom")
        handler = MetricsHandler(self)
        level = logger.level
        if logger.getEffectiveLevel() > logging.INFO:
            logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        try:
            yield
        finally:
            logger.removeHandler(handler)
            logger.setLevel(level)

    def report(self, source: StoreSource, budget: LlmBudget | None) -> MetricsReport:
        c = self.counts
        month = (
            budget.ledger.month(datetime.now(UTC).date().isoformat()) if budget and budget.ledger else None
        )
        llm = LlmMetrics(
            calls=c["llm_calls"],
            errors=c["llm_errors"],
            latency=_latency(self._llm_ms),
            tokens_today=budget.used if budget else 0,
            daily_token_limit=budget.daily_tokens if budget else None,
            month_calls=sum(u.calls for u in month) if month is not None else None,
            month_tokens=sum(u.tokens_in + u.tokens_out for u in month) if month is not None else None,
            month_cost_usd=(
                round(sum(estimated_cost(u.tokens_in, u.tokens_out) for u in month), 4)
                if month is not None
                else None
            ),
            allowance_usd=MONTHLY_ALLOWANCE_USD,
        )
        narrated = c["narratives_verified"] + c["narratives_failed"]
        answered = c["analyst_verified"] + c["analyst_fallback"]
        return MetricsReport(
            contract_version=CONTRACT_VERSION,
            source=source,
            uptime_s=round(self._clock() - self._started),
            requests=RequestMetrics(
                count=c["requests"], errors=c["request_errors"], latency=_latency(self._request_ms)
            ),
            llm=llm,
            narratives=_outcomes(
                c["narratives_verified"],
                c["narratives_failed"] + c["narratives_error"],
                c["narratives_rejected"],
                narrated,
            ),
            analyst=_outcomes(
                c["analyst_verified"],
                c["analyst_fallback"] + c["analyst_error"],
                c["analyst_rejected"],
                answered,
            ),
            replays_active=self.replays_active,
            replays_total=c["replays"],
        )


class MetricsHandler(logging.Handler):
    def __init__(self, metrics: Metrics):
        super().__init__(logging.INFO)
        self.metrics = metrics

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if not message.startswith("{"):
            return
        try:
            event = json.loads(message)
        except json.JSONDecodeError:
            return
        if isinstance(event, dict):
            self.metrics.observe(event)


def timing(metrics: Metrics):
    """HTTP middleware: every request is counted with its route template; only failures and slow requests are
    logged, so Railway's logs stay readable."""

    async def middleware(request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            route = request.scope.get("route")
            path = getattr(route, "path", request.url.path)
            metrics.request(request.method, path, status, (time.perf_counter() - start) * 1000)

    return middleware
