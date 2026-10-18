import json
import logging

from fastapi.testclient import TestClient

from filmroom.agents.layer import AgentLayer
from filmroom.agents.llm import LlmBudget
from filmroom.api.app import create_app
from filmroom.contracts.models import MetricsReport
from filmroom.monitoring import Metrics
from tests.test_engine_store_api import SLUG, _store


def _emit(metrics: Metrics, *events) -> None:
    logger = logging.getLogger("filmroom.narratives")
    with metrics.listening():
        for event in events:
            logger.info(event if isinstance(event, str) else json.dumps(event))


def test_counts_llm_calls_errors_and_latency_from_the_logged_events():
    metrics = Metrics()
    calls = [{"event": "llm_call", "outcome": "ok", "latency_ms": ms} for ms in range(10, 110, 10)]
    _emit(metrics, *calls, {"event": "llm_call", "outcome": "TimeoutError", "latency_ms": 20000})
    budget = LlmBudget(daily_tokens=1000)
    report = metrics.report("engine", budget)
    assert (report.llm.calls, report.llm.errors) == (11, 1)
    assert (report.llm.latency.p50_ms, report.llm.latency.p95_ms) == (60, 20000)
    assert (report.llm.tokens_today, report.llm.daily_token_limit, report.llm.month_tokens) == (0, 1000, None)


def test_derives_fallback_and_rejection_rates_for_narratives_and_the_analyst():
    metrics = Metrics()
    _emit(
        metrics,
        {"event": "narrative", "status": "verified", "rejections": []},
        {"event": "narrative", "status": "verified", "rejections": ["digits: 3"]},
        {"event": "narrative", "status": "failed", "rejections": ["digits: 3", "slot: x"]},
        {"event": "narrative_error", "error": "boom"},
        {"event": "analyst", "status": "verified", "retried": False},
        {"event": "analyst_fallback", "rejections": ["name"]},
    )
    report = metrics.report("engine", None)
    assert report.narratives.model_dump() == {
        "verified": 2,
        "fallback": 2,
        "rejected": 2,
        "fallback_rate": 0.5,
        "rejection_rate": 0.667,
    }
    assert (report.analyst.fallback_rate, report.analyst.rejection_rate) == (0.5, 0.5)


def test_ignores_log_lines_that_are_not_json_events():
    metrics = Metrics()
    _emit(metrics, "plain text", "{not json", json.dumps(["a list"]), {"event": "something_else"})
    report = metrics.report("engine", None)
    assert report.llm.calls == 0 and report.narratives.fallback_rate is None


def test_counts_every_request_and_logs_only_failures_by_route(caplog):
    class Broken:
        def __getattr__(self, name):
            return getattr(store, name)

        def possession(self, possession_id):
            raise RuntimeError("database gone")

    store, metrics = _store(), Metrics()
    client = TestClient(create_app(Broken(), [], metrics=metrics), raise_server_exceptions=False)
    with caplog.at_level(logging.INFO, logger="filmroom.requests"):
        assert client.get(f"/matches/{SLUG}").status_code == 200
        assert client.get(f"/possessions/{SLUG}-1").status_code == 500
    report = metrics.report("engine", None)
    assert (report.requests.count, report.requests.errors) == (2, 1)
    assert [json.loads(r.getMessage()) | {"ms": 0} for r in caplog.records] == [
        {"event": "request", "method": "GET", "route": "/possessions/{possession_id}", "status": 500, "ms": 0}
    ]


def test_metrics_report_validates_and_counts_replays():
    store = _store()
    with TestClient(create_app(store, [], AgentLayer.offline(store))) as client:
        with client.websocket_connect(f"/matches/{SLUG}/replay?speed=10") as socket:
            socket.receive_json()
            assert client.get("/metrics").json()["replays_active"] == 1
        report = MetricsReport.model_validate(client.get("/metrics").json())
    assert (report.source, report.replays_total, report.replays_active) == ("engine", 1, 0)
    assert report.requests.count == 1  # the first /metrics; a request is counted once answered
    assert report.llm.daily_token_limit is None
