"""Parser for the SoccER "Textual annotation(s).txt" event log.

Player references are converted to position IDs (the IDs used in positions.log): team 0 keeps its
text-log ID, team 1 becomes 128 + ID. Lines the parser does not understand are counted, not dropped silently.
"""

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import ClassVar, Literal

import numpy as np

TEAM1_OFFSET = 128

# Frame-prefixed lines that carry nothing the engine uses (per-frame tackle state, debug, assist summaries).
IGNORED_PREFIXES = (
    "AtomicTackle",
    "last opponent position",
    "started tackle",
    "Begin First Half",
    "event: passThenGoal",
    "event: crossThenGoal",
    "event: filteringPassThenGoal",
)

BALL_OUT_RESTARTS = {
    "BallOut - rimessa dal fondo": "goal_kick",
    "BallOut - sideline": "throw_in",
    "BallOut - corner": "corner",
}


@dataclass(frozen=True)
class RosterEntry:
    text_id: int
    pid: int
    team: int
    name: str
    role: Literal["GK", "OUT"]


@dataclass(frozen=True)
class PassStart:
    kind: ClassVar[str] = "pass_start"
    frame: int
    pid: int
    height: Literal["short", "long", "high"]


@dataclass(frozen=True)
class Kick:
    kind: ClassVar[str] = "kick"
    frame: int
    pid: int


@dataclass(frozen=True)
class PassComplete:
    kind: ClassVar[str] = "pass_complete"
    frame: int
    start_frame: int
    pid: int
    receiver: int
    through_ball: bool


@dataclass(frozen=True)
class Cross:
    kind: ClassVar[str] = "cross"
    frame: int
    start_frame: int
    pid: int
    receiver: int
    success: bool


@dataclass(frozen=True)
class Shot:
    kind: ClassVar[str] = "shot"
    frame: int
    start_frame: int
    pid: int
    outcome: Literal["off_target", "saved", "goal"]
    goalkeeper: int | None = None


@dataclass(frozen=True)
class Tackle:
    kind: ClassVar[str] = "tackle"
    frame: int
    start_frame: int
    victim: int
    tackler: int
    outcome: str  # "win" / "lose" as written in the log; whose perspective is resolved in the engine


@dataclass(frozen=True)
class Goal:
    kind: ClassVar[str] = "goal"
    frame: int
    pid: int


@dataclass(frozen=True)
class BallOut:
    kind: ClassVar[str] = "ball_out"
    frame: int
    restart: Literal["goal_kick", "throw_in", "corner"]


@dataclass(frozen=True)
class Foul:
    kind: ClassVar[str] = "foul"
    frame: int
    pid: int
    award: Literal["free_kick", "penalty"]
    card: str | None = None


@dataclass(frozen=True)
class Deflection:
    kind: ClassVar[str] = "deflection"
    frame: int
    pid: int


Event = PassStart | Kick | PassComplete | Cross | Shot | Tackle | Goal | BallOut | Foul | Deflection
EVENT_TYPES: dict[str, type] = {
    t.kind: t for t in (PassStart, Kick, PassComplete, Cross, Shot, Tackle, Goal, BallOut, Foul, Deflection)
}


def event_to_dict(event: Event) -> dict:
    return {"kind": event.kind, **asdict(event)}


def event_from_dict(data: dict) -> Event:
    fields = dict(data)
    return EVENT_TYPES[fields.pop("kind")](**fields)


@dataclass
class TextLog:
    roster: list[RosterEntry]
    possession_frames: np.ndarray  # frames where a player is in possession
    possession_pids: np.ndarray  # that player's position ID
    events: list[Event]
    unparsed: Counter = field(default_factory=Counter)


def to_pid(text_id: int, team: int) -> int:
    return text_id + TEAM1_OFFSET if team == 1 else text_id


def _num(part: str) -> int:
    return int(part.rsplit(":", 1)[1])


def _parts(line: str) -> list[str]:
    return [p.strip() for p in line.rstrip("\n").split("\t") if p.strip()]


def parse_roster(lines: list[str]) -> list[RosterEntry]:
    roster = []
    for line in lines:
        if not line.startswith("playerName:"):
            continue
        name_part, id_part, team_part, role_part = _parts(line)
        text_id, team = _num(id_part), _num(team_part)
        role = "GK" if role_part.split(":", 1)[1].strip() == "goalkeeper" else "OUT"
        roster.append(
            RosterEntry(text_id, to_pid(text_id, team), team, name_part.split(":", 1)[1].strip(), role)
        )
    return roster


def read_roster(path: Path) -> list[RosterEntry]:
    """Read only the header block, so names are available without parsing the whole log."""
    header = []
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("frame:"):
                break
            header.append(line)
    return parse_roster(header)


def parse_textlog(path: Path) -> TextLog:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    roster = parse_roster(lines)
    team_of = {r.text_id: r.team for r in roster}

    def pid(text_id: int) -> int:
        return to_pid(text_id, team_of[text_id])

    poss_frames: list[int] = []
    poss_pids: list[int] = []
    events: list[Event] = []
    shots: dict[tuple[int, int], Shot] = {}
    unparsed: Counter = Counter()

    for i, line in enumerate(lines):
        if not line.startswith("frame:"):
            continue
        p = _parts(line)
        frame = _num(p[0])
        head = p[1] if len(p) > 1 else ""

        if head.startswith("possession player"):
            poss_frames.append(frame)
            poss_pids.append(to_pid(_num(head), _num(p[2])))
        elif head == "KickingTheBall":
            events.append(Kick(frame, to_pid(_num(p[2]), _num(p[3]))))
        elif head.startswith("started ") and head.endswith("Pass"):
            height = head.removeprefix("started ").removesuffix("Pass")
            events.append(PassStart(frame, pid(_num(p[2])), height))
        elif head.startswith("frame start:"):
            start, what = _num(head), p[2]
            if what in ("complete pass", "filteringPass"):
                team = _num(p[5])
                events.append(
                    PassComplete(
                        frame,
                        start,
                        to_pid(_num(p[3]), team),
                        to_pid(_num(p[4]), team),
                        what == "filteringPass",
                    )
                )
            elif what == "cross":
                # A failed cross names the opponent who won it; take the receiver's team from the roster.
                success = p[6].split(":", 1)[1].strip() == "riuscito"
                events.append(Cross(frame, start, to_pid(_num(p[3]), _num(p[5])), pid(_num(p[4])), success))
            elif what == "complete shot (no goal)":
                shooter = to_pid(_num(p[3]), _num(p[4]))
                shots.setdefault((start, shooter), Shot(frame, start, shooter, "off_target"))
            elif what == "saved shot":
                shooter = to_pid(_num(p[3]), _num(p[4]))
                keeper = to_pid(_num(p[5]), _num(p[6]))
                shots[(start, shooter)] = Shot(frame, start, shooter, "saved", keeper)
            elif what == "event: shotThenGoal":
                shooter = to_pid(_num(p[4]), _num(p[3]))
                shots[(start, shooter)] = Shot(frame, start, shooter, "goal")
            elif not what.startswith(IGNORED_PREFIXES):
                unparsed[what] += 1
        elif head == "tackle":
            events.append(
                Tackle(
                    frame,
                    _num(p[2]),
                    to_pid(_num(p[3]), _num(p[4])),
                    to_pid(_num(p[5]), _num(p[6])),
                    p[7].split(":", 1)[1].strip(),
                )
            )
        elif head == "event: goal":
            events.append(Goal(frame, to_pid(_num(p[3]), _num(p[2]))))
        elif head in BALL_OUT_RESTARTS:
            events.append(BallOut(frame, BALL_OUT_RESTARTS[head]))
        elif head == "foul:":
            award = "penalty" if p[2] == "penalty" else "free_kick"
            nxt = _parts(lines[i + 1]) if i + 1 < len(lines) else []
            card = nxt[0].split(":", 1)[1].strip() if nxt and nxt[0].startswith("foul type") else None
            events.append(Foul(frame, to_pid(_num(p[3]), _num(p[4])), award, card))
        elif head == "deflection":
            events.append(Deflection(frame, to_pid(_num(p[2]), _num(p[3]))))
        elif not head.startswith(IGNORED_PREFIXES):
            unparsed[re.sub(r"[-\d.]+", "N", head)[:40]] += 1

    events.extend(shots.values())
    events.sort(key=lambda e: e.frame)
    return TextLog(
        roster,
        np.asarray(poss_frames, dtype=np.int32),
        np.asarray(poss_pids, dtype=np.int16),
        events,
        unparsed,
    )
