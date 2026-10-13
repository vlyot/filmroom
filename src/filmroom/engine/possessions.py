"""Possession splitter, fed one frame at a time so the live replay and offline analysis share one code path.

A possession is an unbroken run of owner rows for one team. The other team's first owner row or first kick
closes it (a clearance can go unlogged as possession), as do ball out, goal and foul. Shots do not: play
continues through rebounds, as in the labelled reference set.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from filmroom.data.catalog import MatchData
from filmroom.data.positions import team_of
from filmroom.data.textlog import BallOut, Event, Foul, Goal, Kick

EndReason = Literal["turnover", "ball_out", "goal", "foul", "match_end"]
STOPPAGES: dict[type, EndReason] = {BallOut: "ball_out", Goal: "goal", Foul: "foul"}


@dataclass
class Spell:
    """One player's uninterrupted time on the ball."""

    pid: int
    first_frame: int
    last_frame: int


@dataclass
class RawPossession:
    team: int
    start_frame: int
    end_frame: int  # last owner row
    close_frame: int = -1  # frame at which the close became known; analysis may read up to here
    end_reason: EndReason = "match_end"
    spells: list[Spell] = field(default_factory=list)


class PossessionSplitter:
    def __init__(self) -> None:
        self.open: RawPossession | None = None

    def step(self, frame: int, owner_pid: int | None, events: Sequence[Event] = ()) -> list[RawPossession]:
        """Advance to `frame`: this frame's stoppages apply first, then its owner row."""
        closed = []
        for event in events:
            reason = STOPPAGES.get(type(event))
            if self.open and isinstance(event, Kick) and team_of(event.pid) != self.open.team:
                reason = "turnover"
            if reason and self.open:
                closed.append(self._close(frame, reason))
        if owner_pid is None:
            return closed
        team = team_of(owner_pid)
        if self.open and self.open.team != team:
            closed.append(self._close(frame, "turnover"))
        if self.open is None:
            self.open = RawPossession(team, frame, frame, spells=[Spell(owner_pid, frame, frame)])
        else:
            self.open.end_frame = frame
            last = self.open.spells[-1]
            if last.pid == owner_pid:
                last.last_frame = frame
            else:
                self.open.spells.append(Spell(owner_pid, frame, frame))
        return closed

    def flush(self, frame: int) -> list[RawPossession]:
        return [self._close(frame, "match_end")] if self.open else []

    def _close(self, frame: int, reason: EndReason) -> RawPossession:
        possession, self.open = self.open, None
        possession.close_frame, possession.end_reason = frame, reason
        return possession


def split_match(md: MatchData) -> list[RawPossession]:
    events_at: dict[int, list[Event]] = defaultdict(list)
    for event in md.events:
        events_at[event.frame].append(event)
    owners = dict(zip(md.possession_frames.tolist(), md.possession_pids.tolist(), strict=True))
    frames = sorted(owners.keys() | events_at.keys())
    splitter = PossessionSplitter()
    possessions = []
    for frame in frames:
        possessions += splitter.step(frame, owners.get(frame), events_at.get(frame, ()))
    last_track = int(md.track.frames[-1]) if len(md.track.frames) else 0
    return possessions + splitter.flush(max(frames[-1] if frames else 0, last_track))
