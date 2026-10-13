"""Scripted synthetic matches for engine tests. CI has no SoccER data, so engine behaviour is pinned on
small hand-written scenarios: a 110 x 72 pitch, 100 frames a second, 10 ms per frame, team 0 attacking
x = 110."""

from pathlib import Path

import numpy as np

from filmroom.data.catalog import MatchData, MatchInfo, Player, TeamInfo
from filmroom.data.frame_times import FrameClock
from filmroom.data.positions import BALL_PID, PositionTrack, team_of
from filmroom.data.textlog import (
    BallOut,
    Cross,
    Event,
    Foul,
    Goal,
    Kick,
    PassComplete,
    PassStart,
    Shot,
    Tackle,
)

SYNTH_MATCH = "Match_2000_01_01_#009"
TEAM0 = list(range(0, 11))
TEAM1 = [128 + i for i in range(18, 29)]
FORMATION = [
    (5, 36),
    (25, 10),
    (25, 28),
    (25, 44),
    (25, 62),
    (45, 12),
    (45, 30),
    (45, 48),
    (45, 64),
    (65, 26),
    (65, 46),
]


class SynthMatch:
    def __init__(self, match_id: str = SYNTH_MATCH):
        self.match_id = match_id
        self.pos = {pid: np.asarray(xy, dtype=float) for pid, xy in zip(TEAM0, FORMATION, strict=True)}
        for pid, (x, y) in zip(TEAM1, FORMATION, strict=True):
            self.pos[pid] = np.asarray((110 - x, 72 - y), dtype=float)
        self.ball = self.pos[6].copy()
        self.frame = 0
        self.rows: list[np.ndarray] = []
        self.owners: list[tuple[int, int]] = []
        self.events: list[Event] = []

    def place(self, pid: int, xy: tuple[float, float]) -> "SynthMatch":
        self.pos[pid] = np.asarray(xy, dtype=float)
        return self

    def _tick(self, owner: int | None = None) -> None:
        self.rows.append(np.stack([self.ball, *(self.pos[p] for p in TEAM0 + TEAM1)]))
        if owner is not None:
            self.owners.append((self.frame, owner))
        self.frame += 1

    def hold(self, pid: int, frames: int, to: tuple[float, float] | None = None) -> "SynthMatch":
        """`pid` keeps the ball for `frames`, dribbling in a straight line to `to` when given."""
        start = self.pos[pid].copy()
        end = np.asarray(to, dtype=float) if to is not None else start
        for i in range(frames):
            self.pos[pid] = start + (end - start) * (i + 1) / frames
            self.ball = self.pos[pid].copy()
            self._tick(owner=pid)
        return self

    def idle(self, frames: int) -> "SynthMatch":
        for _ in range(frames):
            self._tick()
        return self

    def _fly(self, target: np.ndarray, frames: int) -> None:
        origin = self.ball.copy()
        for i in range(frames):
            self.ball = origin + (target - origin) * (i + 1) / frames
            self._tick()

    def pass_to(
        self, passer: int, receiver: int, frames: int = 50, height: str = "short", logged_start: bool = True
    ) -> "SynthMatch":
        start = self.frame
        self.events.append(Kick(start, passer))
        if logged_start:
            self.events.append(PassStart(start, passer, height))
        self._fly(self.pos[receiver].copy(), frames)
        self.events.append(PassComplete(self.frame, start, passer, receiver, False))
        return self

    def cross(self, passer: int, receiver: int, success: bool, frames: int = 60) -> "SynthMatch":
        start = self.frame
        self.events += [Kick(start, passer), PassStart(start, passer, "high")]
        self._fly(self.pos[receiver].copy(), frames)
        self.events.append(Cross(self.frame, start, passer, receiver, success))
        return self

    def intercepted(
        self, passer: int, receiver: int, interceptor: int, at: float = 0.5, frames: int = 30
    ) -> "SynthMatch":
        """A pass aimed at `receiver` that `interceptor` cuts out `at` of the way along; the caller continues
        with the interceptor on the ball."""
        start = self.frame
        self.events += [Kick(start, passer), PassStart(start, passer, "short")]
        point = self.ball + (self.pos[receiver] - self.ball) * at
        self._fly(point, frames)
        self.pos[interceptor] = point.copy()
        return self

    def tackle(self, victim: int, tackler: int, outcome: str = "win") -> "SynthMatch":
        self.pos[tackler] = self.pos[victim] + np.asarray((1.0, 0.0))
        self.events.append(Tackle(self.frame, self.frame - 5, victim, tackler, outcome))
        return self

    def shot(self, pid: int, outcome: str = "off_target", frames: int = 30) -> "SynthMatch":
        start = self.frame
        self.events.append(Kick(start, pid))
        goal = np.asarray((110.0, 36.0) if team_of(pid) == 0 else (0.0, 36.0))
        self._fly(goal, frames)
        self.events.append(Shot(self.frame, start, pid, outcome))
        if outcome == "goal":
            self.events.append(Goal(self.frame + 1, pid))
        return self

    def ball_out(self, frames: int = 50) -> "SynthMatch":
        self.events.append(BallOut(self.frame, "throw_in"))
        return self.idle(frames)

    def foul(self, pid: int, frames: int = 50) -> "SynthMatch":
        self.events.append(Foul(self.frame, pid, "free_kick"))
        return self.idle(frames)

    def build(self) -> MatchData:
        frames = np.arange(len(self.rows), dtype=np.int32)
        pids = np.asarray([BALL_PID, *TEAM0, *TEAM1], dtype=np.int16)
        owner_frames, owner_pids = zip(*self.owners, strict=True) if self.owners else ((), ())
        players = [
            Player(pid, f"p{pid}", f"Player {pid}", i % 11 + 1, team_of(pid), "GK" if i % 11 == 0 else "OUT")
            for i, pid in enumerate(TEAM0 + TEAM1)
        ]
        return MatchData(
            info=MatchInfo(self.match_id, Path(self.match_id), "synthetic", None, None, None),
            clock=FrameClock(frames, frames.astype(np.int64) * 10),
            track=PositionTrack(frames, pids, np.stack(self.rows).astype(np.float32)),
            players=players,
            teams=[TeamInfo(0, "alpha", "Alpha", 110.0), TeamInfo(1, "beta", "Beta", 0.0)],
            possession_frames=np.asarray(owner_frames, dtype=np.int32),
            possession_pids=np.asarray(owner_pids, dtype=np.int16),
            events=sorted(self.events, key=lambda e: e.frame),
            unparsed={},
        )


def counter_attack() -> SynthMatch:
    """Team 0 passes 6 -> 9 -> 10 and loses a pass to 151; team 1 plays on and puts it out of play; team 0
    restarts and shoots wide."""
    m = SynthMatch()
    m.hold(6, 40).pass_to(6, 9).hold(9, 60, to=(72, 26)).pass_to(9, 10)
    m.hold(10, 30).intercepted(10, 9, 151).hold(151, 40).pass_to(151, 153).hold(153, 50).ball_out()
    m.hold(5, 40).pass_to(5, 9).hold(9, 40).shot(9)
    return m
