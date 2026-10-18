"""Live replay: a match clock that plays the store's analyses as they would have arrived.

Every possession was analysed only on data up to the frame it closed, and a test replays a real match frame
by frame to show that gives the same output, so sending a flag as the clock passes the possession's end is
what live analysis would have sent then. Positions go out in one-second slices, a second ahead of the clock,
so the browser can interpolate between samples.
"""

import math
from collections.abc import Awaitable, Callable

import anyio
from anyio.abc import TaskGroup
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from filmroom.api.store import summary_of
from filmroom.contracts.models import Narrative, PositionsChunk, Possession
from filmroom.contracts.ws import (
    ClientMessage,
    Clock,
    Control,
    ErrorMessage,
    MatchEnd,
    NarrativeReady,
    PositionsMessage,
    PossessionFlagged,
)

TICK_S = 0.1
SLICE_MS = 1000
MIN_SPEED, MAX_SPEED = 1.0, 10.0
NARRATIVE_WAIT_S = 120

type ServerMsg = Clock | PositionsMessage | PossessionFlagged | NarrativeReady | MatchEnd | ErrorMessage
PositionsLookup = Callable[[str], Awaitable[PositionsChunk | None]]


def slice_chunk(chunk: PositionsChunk, t0_ms: float, t1_ms: float) -> PositionsChunk | None:
    """The samples timed in [t0_ms, t1_ms), or None when there are none."""
    step = 1000 / chunk.hz
    first = max(0, math.ceil((t0_ms - chunk.t0_ms) / step))
    stop = min(len(chunk.xy), math.ceil((t1_ms - chunk.t0_ms) / step))
    if first >= stop:
        return None
    return chunk.model_copy(update={"t0_ms": round(chunk.t0_ms + first * step), "xy": chunk.xy[first:stop]})


def _speed(value: float) -> float:
    return min(MAX_SPEED, max(MIN_SPEED, value))


class ReplaySession:
    """One viewer's replay of one match. `advance` moves the clock by wall time × speed and returns what to
    send; `control` applies play, pause, speed and seek."""

    def __init__(
        self,
        possessions: list[Possession],
        duration_ms: int,
        positions: PositionsLookup,
        narrate: Callable[[Possession], Narrative],
        speed: float = 1.0,
        from_ms: int = 0,
    ):
        self.possessions = sorted(possessions, key=lambda p: p.start_ms)
        self.duration_ms = duration_ms
        self.positions = positions
        self.narrate = narrate
        self.speed = _speed(speed)
        self.playing = True
        self.t_ms = 0.0
        self._sent: set[str] = set()
        self._chunks: dict[str, PositionsChunk | None] = {}
        self._dirty = True
        self._seek(from_ms)

    def _seek(self, t_ms: float) -> None:
        self.t_ms = min(float(self.duration_ms), max(0.0, t_ms))
        self._sliced_to = self.t_ms
        self._ended = self.t_ms >= self.duration_ms
        self._sent = {pid for pid in self._sent if self._by_id(pid).end_ms <= self.t_ms}

    def _by_id(self, possession_id: str) -> Possession:
        return next(p for p in self.possessions if p.id == possession_id)

    def clock(self) -> Clock:
        return Clock(t_ms=round(self.t_ms), speed=self.speed, playing=self.playing)

    async def advance(self, wall_ms: float) -> list[ServerMsg]:
        if self.playing:
            self.t_ms = min(float(self.duration_ms), self.t_ms + wall_ms * self.speed)
        reached_end = self.t_ms >= self.duration_ms and not self._ended
        if reached_end:
            self._ended, self.playing = True, False
        messages: list[ServerMsg] = []
        if self.playing or self._dirty or reached_end:
            messages.append(self.clock())
            self._dirty = False
        messages += await self._position_slices()
        messages += self._flags()
        if reached_end:
            messages.append(MatchEnd())
        return messages

    def control(self, control: Control) -> list[ServerMsg]:
        match control.action:
            case "play":
                if self._ended:
                    self._seek(0)
                self.playing = True
            case "pause":
                self.playing = False
            case "speed" | "seek" if control.value is None:
                return [ErrorMessage(message=f"{control.action} needs a value")]
            case "speed":
                self.speed = _speed(control.value)
            case "seek":
                self._seek(control.value)
        self._dirty = True
        return []

    async def _position_slices(self) -> list[PositionsMessage]:
        messages = []
        horizon = min(float(self.duration_ms), self.t_ms + SLICE_MS)
        while self._sliced_to < horizon:
            start, stop = self._sliced_to, min(horizon, self._sliced_to + SLICE_MS)
            for possession in self.possessions:
                if possession.start_ms < stop and possession.end_ms >= start:
                    chunk = await self._chunk(possession.id)
                    if chunk and (part := slice_chunk(chunk, start, stop)):
                        messages.append(PositionsMessage(chunk=part))
            self._sliced_to = stop
            self._chunks = {
                pid: chunk for pid, chunk in self._chunks.items() if self._by_id(pid).end_ms >= stop
            }
        return messages

    async def _chunk(self, possession_id: str) -> PositionsChunk | None:
        if possession_id not in self._chunks:
            self._chunks[possession_id] = await self.positions(possession_id)
        return self._chunks[possession_id]

    def _flags(self) -> list[PossessionFlagged]:
        due = [p for p in self.possessions if p.flagged and p.end_ms <= self.t_ms and p.id not in self._sent]
        self._sent |= {p.id for p in due}
        return [PossessionFlagged(summary=summary_of(p), narrative=self.narrate(p)) for p in due]


class ReplayChannel:
    """One replay WebSocket: sends are serialised, and narrative pushes end with the socket. Runs on an anyio
    task group, as Starlette does, so a client leaving mid-send or the server cancelling ends it cleanly."""

    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self._lock = anyio.Lock()
        self._group: TaskGroup | None = None

    async def send(self, messages: list[ServerMsg]) -> None:
        async with self._lock:
            for message in messages:
                await self.websocket.send_text(message.model_dump_json())

    def push_when_ready(self, ready: Awaitable[Narrative | None]) -> None:
        """Sends the narrative `ready` resolves to, once it does; nothing if it resolves to None. Only while
        `run` is running."""

        async def push() -> None:
            if (narrative := await ready) is not None:
                await self.send([NarrativeReady(narrative=narrative)])

        self._group.start_soon(push)

    async def run(self, session: ReplaySession) -> None:
        """Ticks the session and applies control messages until the client goes away."""

        async def tick() -> None:
            last = anyio.current_time()
            await self.send(await session.advance(0))
            while True:
                await anyio.sleep(TICK_S)
                now = anyio.current_time()
                await self.send(await session.advance((now - last) * 1000))
                last = now

        try:
            async with anyio.create_task_group() as group:
                self._group = group
                group.start_soon(tick)
                while True:
                    raw = await self.websocket.receive_text()
                    try:
                        control = ClientMessage.model_validate_json(raw).root
                    except ValidationError:
                        await self.send([ErrorMessage(message="not a control message")])
                        continue
                    await self.send(session.control(control))
        except* WebSocketDisconnect:
            pass
