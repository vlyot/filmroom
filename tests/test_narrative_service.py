import asyncio

from filmroom.agents import narrator as narrator_module
from filmroom.agents.cache import JsonCache
from filmroom.agents.llm import LlmBudget
from filmroom.agents.narratives import NarrativeService
from filmroom.agents.narrator import NarrationRequest, NarrationResult, Narrator
from filmroom.contracts.models import Narrative
from tests.agent_fakes import REFERENCE, STYLES, ScriptedChatClient, synth


def _request(index: int = 0, style=REFERENCE, audience="coach", severity: float | None = None):
    match, possessions = synth()
    possession = possessions[index]
    if severity is not None:
        possession = possession.model_copy(update={"severity": severity})
    return NarrationRequest(possession, match, style, REFERENCE, audience, "en")


class RecordingNarrator:
    """Stands in for the narrator where only the order and number of calls matter."""

    model = "recording"

    def __init__(self, error: Exception | None = None):
        self.calls: list[NarrationRequest] = []
        self.error = error

    async def generate(self, request: NarrationRequest) -> NarrationResult:
        self.calls.append(request)
        if self.error:
            raise self.error
        verified = request.template().model_copy(update={"status": "verified", "model": self.model})
        return NarrationResult(verified, [])


async def _drain(service: NarrativeService) -> None:
    for _ in range(200):
        if not service._heap and not service._queued:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the queue never emptied")


def test_returns_the_template_at_once_then_the_verified_narrative():
    request = _request()
    template = request.template()
    draft = {"text": template.template, "claims": [c.model_dump() for c in template.claims]}
    narrator = Narrator(ScriptedChatClient([draft]), "scripted-model")
    service = NarrativeService(narrator, JsonCache(None))

    async def go() -> tuple[Narrative, Narrative]:
        service.start()
        first = service.get(request)
        await _drain(service)
        second = service.get(request)
        await service.stop()
        return first, second

    first, second = asyncio.run(go())
    assert first.status == "pending" and first.template == request.template().template
    assert second.status == "verified" and second.model == "scripted-model"


def test_serves_a_cached_narrative_without_a_call():
    request = _request()
    narrator = RecordingNarrator()
    cache = JsonCache(None)
    verified = request.template().model_copy(update={"status": "verified"})
    cache.put(request.cache_key(narrator.model), verified)
    assert NarrativeService(narrator, cache).get(request) == verified
    assert narrator.calls == []


def test_runs_on_demand_jobs_first_then_flags_by_severity_then_recency():
    narrator = RecordingNarrator()
    service = NarrativeService(narrator, JsonCache(None), concurrency=1)
    mild, severe, severe_newer = (
        _request(0, severity=0.2),
        _request(1, severity=0.9),
        _request(2, severity=0.9),
    )
    opened_first, opened_last = _request(0, audience="fan"), _request(1, audience="fan")

    async def go():
        for request in (mild, severe, severe_newer):
            service.enqueue_flagged(request)
        service.get(opened_first)
        service.get(opened_last)
        service.start()
        await _drain(service)
        await service.stop()

    asyncio.run(go())
    assert narrator.calls == [opened_last, opened_first, severe_newer, severe, mild]


def test_drops_the_lowest_flag_time_job_when_the_queue_is_full():
    narrator = RecordingNarrator()
    service = NarrativeService(narrator, JsonCache(None), concurrency=1, max_flagged=2)
    requests = [_request(i, severity=s) for i, s in enumerate((0.5, 0.1, 0.8))]

    async def go():
        for request in requests:
            service.enqueue_flagged(request)
        service.start()
        await _drain(service)
        await service.stop()

    asyncio.run(go())
    assert narrator.calls == [requests[2], requests[0]]


def test_dedupes_requests_for_the_same_narrative():
    narrator = RecordingNarrator()
    service = NarrativeService(narrator, JsonCache(None))
    request = _request()

    async def go():
        service.enqueue_flagged(request)
        assert service.get(request).status == "pending"
        assert service.get(request).status == "pending"
        service.start()
        await _drain(service)
        await service.stop()

    asyncio.run(go())
    assert len(narrator.calls) == 1


def test_stops_calling_the_llm_once_the_daily_tokens_are_spent():
    narrator = RecordingNarrator()
    budget = LlmBudget(daily_tokens=0)
    service = NarrativeService(narrator, JsonCache(None), budget)
    request = _request()
    service.enqueue_flagged(request)
    assert service.get(request).status == "template" and not service._heap


def test_offline_service_serves_cached_narratives_for_its_model_and_templates_otherwise():
    request, cache = _request(), JsonCache(None)
    verified = request.template().model_copy(update={"status": "verified"})
    cache.put(request.cache_key("m"), verified)
    assert NarrativeService(None, cache, model="m").get(request) == verified
    assert NarrativeService(None, cache).get(request).status == "template"
    assert NarrativeService(None, cache, model="other").get(_request(1)).status == "template"


def test_keys_on_the_verdict_the_style_and_the_prompt_version(monkeypatch):
    request = _request()
    key = request.cache_key("m")
    assert _request(style=STYLES[2]).cache_key("m") != key
    verdicts = dict(request.possession.verdicts)
    verdicts[REFERENCE.id] = verdicts[REFERENCE.id].model_copy(update={"best_option_id": "d2.carry"})
    changed = NarrationRequest(
        request.possession.model_copy(update={"verdicts": verdicts}),
        request.match, REFERENCE, REFERENCE, "coach", "en",
    )  # fmt: skip
    assert changed.cache_key("m") != key
    monkeypatch.setattr(narrator_module, "NARRATOR_VERSION", 99)
    assert request.cache_key("m") != key


def test_does_not_cache_llm_errors_and_backs_off():
    narrator = RecordingNarrator(error=TimeoutError())
    cache = JsonCache(None)
    service = NarrativeService(narrator, cache, backoff_s=60)
    request = _request()

    async def go() -> Narrative:
        service.start()
        service.get(request)
        await _drain(service)
        after = service.get(request)
        await service.stop()
        return after

    assert asyncio.run(go()).status == "failed"
    assert cache.get(request.cache_key(narrator.model), Narrative) is None
    assert len(narrator.calls) == 1


def test_wait_returns_the_verified_narrative_or_the_pending_template_on_timeout():
    request = _request()

    async def go(narrator, timeout) -> Narrative:
        service = NarrativeService(narrator, JsonCache(None))
        service.start()
        narrative = await service.wait(request, timeout)
        await service.stop()
        return narrative

    assert asyncio.run(go(RecordingNarrator(), 1)).status == "verified"

    class Slow(RecordingNarrator):
        async def generate(self, request):
            await asyncio.sleep(1)
            return await super().generate(request)

    assert asyncio.run(go(Slow(), 0.05)).status == "pending"
