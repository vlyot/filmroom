"""Decisions inside a possession, and how each one turned out.

A decision is a moment the player on the ball chose an action: a pass (logged as PassStart, as a completion or
cross with no PassStart, or as a bare kick), a shot, or a final dribble when the last ball carrier lost the
ball without releasing it. Callers pass `md` cut at the possession's close frame, so nothing here can look
past it.
"""

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np

from filmroom.contracts.models import ActionKind
from filmroom.data.catalog import MatchData
from filmroom.data.positions import BALL_PID, team_of
from filmroom.data.textlog import Cross, Goal, Kick, PassComplete, PassStart, Shot, Tackle
from filmroom.engine.geometry import PITCH, attacking
from filmroom.engine.possessions import RawPossession

MERGE_FRAMES = 3  # PassStart, Kick and completion lines for one pass can sit a frame or two apart
CARRY_LEAD_FRAMES = 50  # a lost dribble is judged half a second before the last touch, while passing was on
TARGET_LOOK_FRAMES = 100
TARGET_LAG_FRAMES = 50  # receivers move to meet the ball; where they are half a second on shows the intent
TARGET_MAX_ANGLE = math.radians(60)
TARGET_DEPTH_WEIGHT = 0.1
NEXT_OWNER_FRAMES = 400

Outcome = Literal["shot", "goal", "lost_tackle", "lost_pass", "out", "stoppage"]
Zone = Literal["own", "mid", "final"]


@dataclass(frozen=True)
class RawDecision:
    frame: int
    pid: int
    kind: ActionKind
    completed: bool | None = None
    target_pid: int | None = None
    target_xy: tuple[float, float] | None = None  # pitch coordinates
    height: str | None = None


def _xy(md: MatchData, frame: int, pid: int) -> np.ndarray:
    row = min(int(np.searchsorted(md.track.frames, frame)), len(md.track.frames) - 1)
    return md.track.xy[row, int(np.flatnonzero(md.track.pids == pid)[0])].astype(float)


def _point(xy: np.ndarray) -> tuple[float, float]:
    return (round(float(xy[0]), 2), round(float(xy[1]), 2))


def next_owner(md: MatchData, after: int, within: int = NEXT_OWNER_FRAMES) -> int | None:
    i = int(np.searchsorted(md.possession_frames, after, side="right"))
    if i < len(md.possession_frames) and md.possession_frames[i] <= after + within:
        return int(md.possession_pids[i])
    return None


def intended_target(
    md: MatchData, frame: int, passer: int, until: int
) -> tuple[int | None, tuple[float, float]]:
    """Where a pass with no logged receiver was going: the teammate, ahead of the passer and within 60 degrees
    of the ball's path, who is closest to that path and to how far the ball travelled. With no such teammate,
    the furthest point the ball reached. Finds the logged receiver of 84% of completed passes."""
    n = len(md.track.frames)
    lo = min(int(np.searchsorted(md.track.frames, frame)), n - 1)
    hi = max(
        lo + 1, int(np.searchsorted(md.track.frames, min(frame + TARGET_LOOK_FRAMES, until), side="right"))
    )
    path = md.track.xy[lo:hi, 0].astype(float)
    origin = path[0]
    far = path[int(np.argmax(np.linalg.norm(path - origin, axis=1)))]
    travel = float(np.linalg.norm(far - origin))
    if travel < 2.0:
        return None, _point(far)
    direction = (far - origin) / travel
    lagged = md.track.xy[min(lo + TARGET_LAG_FRAMES, n - 1)].astype(float)
    best, best_score = None, math.inf
    for i, pid in enumerate(md.track.pids.tolist()):
        if pid == passer or i == 0 or team_of(pid) != team_of(passer):
            continue
        v = lagged[i] - origin
        along = float(v @ direction)
        across = abs(float(v[0] * direction[1] - v[1] * direction[0]))
        score = across + TARGET_DEPTH_WEIGHT * abs(along - travel)
        if along > 0 and math.atan2(across, along) <= TARGET_MAX_ANGLE and score < best_score:
            best, best_score = pid, score
    if best is None:
        return None, _point(far)
    return best, _point(_xy(md, frame, best))


def extract_decisions(md: MatchData, poss: RawPossession) -> list[RawDecision]:
    lo, hi = poss.start_frame, poss.close_frame
    candidates: list[tuple[int, int, int, ActionKind]] = []  # frame, priority, pid, kind
    receivers: dict[int, tuple[int, bool]] = {}
    heights: dict[int, str] = {}
    for e in md.events:
        if isinstance(e, PassStart | Kick) and lo <= e.frame <= hi and team_of(e.pid) == poss.team:
            candidates.append((e.frame, 1 if isinstance(e, PassStart) else 3, e.pid, "pass"))
            if isinstance(e, PassStart):
                heights[e.frame] = e.height
        elif (
            isinstance(e, PassComplete | Cross) and lo <= e.start_frame <= hi and team_of(e.pid) == poss.team
        ):
            candidates.append((e.start_frame, 2, e.pid, "pass"))
            if team_of(e.receiver) == poss.team:
                receivers[e.start_frame] = (e.receiver, e.success if isinstance(e, Cross) else True)
            if isinstance(e, Cross):
                heights[e.start_frame] = "high"
        elif isinstance(e, Shot) and lo <= e.start_frame <= hi and team_of(e.pid) == poss.team:
            candidates.append((e.start_frame, 0, e.pid, "shot"))

    groups: list[list[tuple[int, int, int, ActionKind]]] = []
    for c in sorted(candidates):
        if groups and c[0] - groups[-1][0][0] <= MERGE_FRAMES:
            groups[-1].append(c)
        else:
            groups.append([c])

    decisions = []
    for n, group in enumerate(groups):
        frame = group[0][0]
        _, _, pid, kind = min(group, key=lambda c: c[1])
        if kind == "shot":
            decisions.append(RawDecision(frame, pid, "shot"))
            continue
        frames = {c[0] for c in group}
        logged = next((receivers[f] for f in sorted(frames) if f in receivers), None)
        height = next((heights[f] for f in sorted(frames) if f in heights), None)
        until = groups[n + 1][0][0] if n + 1 < len(groups) else hi
        if logged is None:
            owner = next_owner(md, frame)
            if owner is not None and owner != pid and team_of(owner) == poss.team:
                logged = (owner, True)
        if (
            logged is not None and logged[0] == pid
        ):  # knocked on and collected again: a dribble that kept the ball
            decisions.append(RawDecision(frame, pid, "carry", True, target_xy=_point(_xy(md, frame, pid))))
            continue
        if logged is not None:
            receiver, completed = logged
            target = _point(_xy(md, frame, receiver))
        else:
            completed = False
            receiver, target = intended_target(md, frame, pid, until)
        decisions.append(RawDecision(frame, pid, "pass", completed, receiver, target, height))

    last = poss.spells[-1]
    released = any(d.pid == last.pid and d.frame >= last.first_frame for d in decisions)
    if poss.end_reason in ("turnover", "ball_out") and not released:
        frame = max(last.last_frame - CARRY_LEAD_FRAMES, last.first_frame)
        decisions.append(
            RawDecision(frame, last.pid, "carry", target_xy=_point(_xy(md, last.last_frame, last.pid)))
        )
    return decisions


def tackle_winner(md: MatchData, tackle: Tackle) -> int:
    """The side that has the ball next. The log's win/lose has no stated perspective, so it is only a
    fallback, read as the tackler's."""
    owner = next_owner(md, tackle.frame, within=200)
    if owner is not None:
        return team_of(owner)
    return team_of(tackle.tackler) if tackle.outcome == "win" else team_of(tackle.victim)


def possession_outcome(
    md: MatchData, poss: RawPossession, decisions: list[RawDecision]
) -> tuple[Outcome, Zone]:
    in_poss = [e for e in md.events if poss.start_frame <= e.frame <= poss.close_frame]
    last = decisions[-1] if decisions else None
    outcome: Outcome
    if any(isinstance(e, Goal) and team_of(e.pid) == poss.team for e in in_poss):
        outcome = "goal"
    elif last is not None and last.kind == "shot":
        outcome = "shot"
    elif poss.end_reason == "ball_out":
        outcome = "out"
    elif poss.end_reason != "turnover":
        outcome = "stoppage"
    elif any(
        isinstance(e, Tackle) and e.frame >= poss.spells[-1].first_frame and tackle_winner(md, e) != poss.team
        for e in in_poss
    ):
        outcome = "lost_tackle"
    elif last is not None and last.kind == "pass" and not last.completed:
        outcome = "lost_pass"
    else:
        outcome = "lost_tackle"
    x = float(attacking(_xy(md, poss.end_frame, BALL_PID), poss.team)[0])
    zone: Zone = "own" if x < PITCH[0] / 3 else "final" if x > 2 * PITCH[0] / 3 else "mid"
    return outcome, zone
