"""The narrative service: the template at once, the verified narrative once one exists.

`get` never waits on the LLM. It returns a cached narrative, or the template with status `pending` and a job
in the queue. Without a narrator (no key, or the bundle exporter) it still serves cached narratives for
`model`, and templates otherwise. On-demand jobs (someone opened the moment) run before flag-time jobs
(`enqueue_flagged`, for the live replay), newest first; flag-time jobs run most severe first, and only the
top `max_flagged` are kept, so low-ranked flags keep their template until someone opens them. Verifier
failures are cached, so a moment that can't be narrated isn't paid for twice; LLM errors are not, and the
key backs off for a while.

Every method runs on the event loop: routes call `get` from async handlers.
"""

import asyncio
import heapq
import itertools
import json
import logging
import time
from dataclasses import dataclass, field

from filmroom.agents.cache import JsonCache
from filmroom.agents.llm import LlmBudget
from filmroom.agents.narrator import NarrationRequest, Narrator
from filmroom.contracts.models import Narrative

log = logging.getLogger("filmroom.narratives")
ON_DEMAND, FLAG_TIME = 0, 1


@dataclass(order=True)
class _Job:
    priority: tuple[int, float, int]
    key: str = field(compare=False)
    request: NarrationRequest = field(compare=False)


class NarrativeService:
    def __init__(
        self,
        narrator: Narrator | None,
        cache: JsonCache,
        budget: LlmBudget | None = None,
        model: str | None = None,
        concurrency: int = 2,
        max_flagged: int = 20,
        backoff_s: float = 120,
    ):
        self.narrator = narrator
        self.model = narrator.model if narrator else model
        self.cache = cache
        self.budget = budget
        self.concurrency = concurrency
        self.max_flagged = max_flagged
        self.backoff_s = backoff_s
        self._heap: list[_Job] = []
        self._queued: dict[str, _Job] = {}
        self._done: dict[str, asyncio.Event] = {}
        self._backoff_until: dict[str, float] = {}
        self._wakeup = asyncio.Event()
        self._order = itertools.count()
        self._workers: list[asyncio.Task] = []

    @property
    def live(self) -> bool:
        return self.narrator is not None and not (self.budget and self.budget.exhausted)

    def _key(self, request: NarrationRequest) -> str | None:
        return request.cache_key(self.model) if self.model else None

    def get(self, request: NarrationRequest) -> Narrative:
        key = self._key(request)
        if key and (cached := self.cache.get(key, Narrative)):
            return cached
        template = request.template()
        if key is None or not self.live:
            return template
        if self._backoff_until.get(key, 0) > time.monotonic():
            return template.model_copy(update={"status": "failed"})
        self._submit(key, request, ON_DEMAND)
        return template.model_copy(update={"status": "pending"})

    def enqueue_flagged(self, request: NarrationRequest) -> None:
        key = self._key(request)
        if key and self.live and not self.cache.get(key, Narrative):
            self._submit(key, request, FLAG_TIME)

    async def wait(self, request: NarrationRequest, timeout: float) -> Narrative:
        narrative = self.get(request)
        if narrative.status == "pending" and (key := self._key(request)) in self._done:
            try:
                await asyncio.wait_for(self._done[key].wait(), timeout)
            except TimeoutError:
                return narrative
            return self.get(request)
        return narrative

    def _submit(self, key: str, request: NarrationRequest, tier: int) -> None:
        severity = request.possession.severity if tier == FLAG_TIME else 0.0
        job = _Job((tier, -severity, -next(self._order)), key, request)
        if (queued := self._queued.get(key)) is not None:
            if queued.priority[0] <= tier or queued not in self._heap:
                return
            self._heap.remove(queued)
            heapq.heapify(self._heap)
        self._queued[key] = job
        self._done.setdefault(key, asyncio.Event())
        heapq.heappush(self._heap, job)
        flagged = [j for j in self._heap if j.priority[0] == FLAG_TIME]
        if len(flagged) > self.max_flagged:
            dropped = max(flagged)
            self._heap.remove(dropped)
            heapq.heapify(self._heap)
            self._finish(dropped.key)
        self._wakeup.set()

    def _finish(self, key: str) -> None:
        self._queued.pop(key, None)
        if event := self._done.pop(key, None):
            event.set()

    async def _next_job(self) -> _Job:
        while not self._heap:
            self._wakeup.clear()
            await self._wakeup.wait()
        return heapq.heappop(self._heap)

    async def _work(self) -> None:
        while True:
            job = await self._next_job()
            request = job.request
            record = {
                "possession": request.possession.id,
                "style": request.style.id,
                "audience": request.audience,
                "language": request.language,
            }
            try:
                result = await self.narrator.generate(request)
            except Exception as error:  # LLM errors, the allowance, timeouts: retry after the backoff
                self._backoff_until[job.key] = time.monotonic() + self.backoff_s
                log.warning(json.dumps({"event": "narrative_error", **record, "error": repr(error)[:300]}))
            else:
                self.cache.put(job.key, result.narrative)
                rejections = [f"{r.code}: {r.detail}"[:200] for r in result.rejections]
                record |= {"status": result.narrative.status, "rejections": rejections}
                log.info(json.dumps({"event": "narrative", **record}))
            finally:
                self._finish(job.key)

    def start(self) -> None:
        if self.narrator is not None and not self._workers:
            self._workers = [asyncio.create_task(self._work()) for _ in range(self.concurrency)]

    async def stop(self) -> None:
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []
