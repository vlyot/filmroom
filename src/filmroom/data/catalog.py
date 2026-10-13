"""Match catalog: lists the SoccER matches and loads one match with fictional identities applied.

Parsed matches are cached under CACHE_DIR/matches, keyed by the loader version and the source files' size and
modification time. The cache holds raw roster names; it is local-only and gitignored.
"""

import json
from bisect import bisect_right
from dataclasses import asdict, dataclass, replace
from functools import cached_property
from pathlib import Path

import numpy as np

from filmroom.config import Settings
from filmroom.data import files
from filmroom.data.frame_times import FrameClock
from filmroom.data.identity import IdentityMap, build_identity
from filmroom.data.positions import BALL_PID, PositionTrack, parse_positions
from filmroom.data.textlog import (
    Event,
    RosterEntry,
    TextLog,
    event_from_dict,
    event_to_dict,
    parse_textlog,
    read_roster,
)

LOADER_VERSION = 2
MIN_EVENTS = 100  # below this the text log is treated as broken (09_13 #001 is truncated)
ATTACKS_TOWARDS_X = {0: 110.0, 1: 0.0}
METADATA = json.loads(Path(__file__).with_name("matches.json").read_text(encoding="utf-8"))


@dataclass(frozen=True)
class MatchInfo:
    id: str
    dir: Path
    mode: str
    video_offset_s: float | None
    textlog: Path | None
    video: Path | None


@dataclass(frozen=True)
class Player:
    pid: int
    key: str
    name: str
    shirt: int
    team: int
    role: str


@dataclass(frozen=True)
class TeamInfo:
    side: int
    key: str
    name: str
    attacks_towards_x: float


@dataclass
class MatchData:
    info: MatchInfo
    clock: FrameClock
    track: PositionTrack
    players: list[Player]
    teams: list[TeamInfo]
    possession_frames: np.ndarray
    possession_pids: np.ndarray
    events: list[Event]
    unparsed: dict[str, int]

    @property
    def has_events(self) -> bool:
        return len(self.events) >= MIN_EVENTS

    def player(self, pid: int) -> Player:
        return next(p for p in self.players if p.pid == pid)

    def until(self, frame: int) -> "MatchData":
        """The match as it stood at `frame`: nothing logged later is visible, which is what keeps live
        analysis free of lookahead. Arrays are views, so this is cheap."""

        def upto(frames: np.ndarray) -> int:
            return int(np.searchsorted(frames, frame, side="right"))

        n_track, n_clock = upto(self.track.frames), upto(self.clock.frames)
        n_poss = upto(self.possession_frames)
        return replace(
            self,
            clock=FrameClock(self.clock.frames[:n_clock], self.clock.ms[:n_clock]),
            track=PositionTrack(self.track.frames[:n_track], self.track.pids, self.track.xy[:n_track]),
            possession_frames=self.possession_frames[:n_poss],
            possession_pids=self.possession_pids[:n_poss],
            events=self.events[: bisect_right(self.events, frame, key=lambda e: e.frame)],
        )


def match_slug(match_id: str) -> str:
    """URL- and filename-safe ID: Match_2019_09_09_#001 -> 2019_09_09_001."""
    return match_id.removeprefix("Match_").replace("#", "")


def _shirts(roster: list[RosterEntry]) -> dict[int, int]:
    shirts = {}
    for side in (0, 1):
        side_roster = sorted((r for r in roster if r.team == side), key=lambda r: (r.role != "GK", r.text_id))
        shirts.update({r.pid: n for n, r in enumerate(side_roster, start=1)})
    return shirts


class Catalog:
    def __init__(self, settings: Settings):
        if settings.data_dir is None or not settings.data_dir.is_dir():
            raise FileNotFoundError("DATA_DIR is not set or does not exist; see README > Data")
        self.data_dir = settings.data_dir
        self.cache_dir = settings.cache_dir / "matches"

    def matches(self) -> list[MatchInfo]:
        return [self._info(d) for d in sorted(self.data_dir.glob("Match_*")) if d.is_dir()]

    def info(self, match_id: str) -> MatchInfo:
        return self._info(self.data_dir / match_id)

    def by_slug(self, slug: str) -> MatchInfo:
        for info in self.matches():
            if match_slug(info.id) == slug:
                return info
        raise KeyError(f"not found: {slug}")

    def _info(self, match_dir: Path) -> MatchInfo:
        meta = METADATA.get(match_dir.name, {})
        return MatchInfo(
            id=match_dir.name,
            dir=match_dir,
            mode=meta.get("mode", "unknown"),
            video_offset_s=meta.get("video_offset_s"),
            textlog=files.resolve(match_dir, *files.TEXTLOG),
            video=files.resolve(match_dir, *files.VIDEO),
        )

    @cached_property
    def identity(self) -> IdentityMap:
        return build_identity({m.id: read_roster(m.textlog) if m.textlog else [] for m in self.matches()})

    def load(self, match_id: str, use_cache: bool = True) -> MatchData:
        info = self.info(match_id)
        sources = [
            files.resolve(info.dir, *files.POSITIONS),
            files.resolve(info.dir, *files.FRAME_TIMES),
            info.textlog,
        ]
        signature = [LOADER_VERSION] + [
            [p.name, p.stat().st_size, p.stat().st_mtime_ns] for p in sources if p
        ]
        cached = self._read_cache(match_id, signature) if use_cache else None
        if cached is None:
            track = parse_positions(sources[0])
            clock = FrameClock.from_csv(sources[1])
            textlog = parse_textlog(info.textlog) if info.textlog else None
            self._write_cache(match_id, signature, track, clock, textlog)
        else:
            track, clock, textlog = cached
        return self._assemble(info, track, clock, textlog)

    def _assemble(
        self, info: MatchInfo, track: PositionTrack, clock: FrameClock, textlog: TextLog | None
    ) -> MatchData:
        roster = textlog.roster if textlog else []
        shirts = _shirts(roster)
        by_pid = {r.pid: r for r in roster}
        players = []
        for slot, pid in enumerate(int(p) for p in track.pids if p != BALL_PID):
            team = 1 if pid > BALL_PID else 0
            if pid in by_pid:
                who = self.identity.player(info.id, team, by_pid[pid].name)
                players.append(Player(pid, who.key, who.name, shirts[pid], team, by_pid[pid].role))
            else:
                shirt = slot % 11 + 1
                players.append(Player(pid, f"anon_{info.id}_{pid}", f"Player {shirt}", shirt, team, "OUT"))
        teams = [
            TeamInfo(side, club.key, club.name, ATTACKS_TOWARDS_X[side])
            for side in (0, 1)
            for club in [self.identity.team(info.id, side)]
        ]
        empty = np.asarray([], dtype=np.int32)
        return MatchData(
            info=info,
            clock=clock,
            track=track,
            players=players,
            teams=teams,
            possession_frames=textlog.possession_frames if textlog else empty,
            possession_pids=textlog.possession_pids if textlog else empty,
            events=textlog.events if textlog else [],
            unparsed=dict(textlog.unparsed) if textlog else {},
        )

    def _paths(self, match_id: str) -> tuple[Path, Path]:
        return self.cache_dir / f"{match_id}.npz", self.cache_dir / f"{match_id}.json"

    def _write_cache(
        self, match_id: str, signature: list, track: PositionTrack, clock: FrameClock, textlog: TextLog | None
    ) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        arrays_path, meta_path = self._paths(match_id)
        np.savez_compressed(
            arrays_path,
            frames=track.frames,
            pids=track.pids,
            xy=track.xy,
            clock_frames=clock.frames,
            clock_ms=clock.ms,
            poss_frames=textlog.possession_frames if textlog else np.asarray([], dtype=np.int32),
            poss_pids=textlog.possession_pids if textlog else np.asarray([], dtype=np.int16),
        )
        meta = {
            "signature": signature,
            "has_textlog": textlog is not None,
            "roster": [asdict(r) for r in textlog.roster] if textlog else [],
            "events": [event_to_dict(e) for e in textlog.events] if textlog else [],
            "unparsed": dict(textlog.unparsed) if textlog else {},
        }
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

    def _read_cache(
        self, match_id: str, signature: list
    ) -> tuple[PositionTrack, FrameClock, TextLog | None] | None:
        arrays_path, meta_path = self._paths(match_id)
        if not (arrays_path.exists() and meta_path.exists()):
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta["signature"] != json.loads(json.dumps(signature)):
            return None
        a = np.load(arrays_path)
        track = PositionTrack(a["frames"], a["pids"], a["xy"])
        clock = FrameClock(a["clock_frames"], a["clock_ms"])
        textlog = None
        if meta["has_textlog"]:
            textlog = TextLog(
                roster=[RosterEntry(**r) for r in meta["roster"]],
                possession_frames=a["poss_frames"],
                possession_pids=a["poss_pids"],
                events=[event_from_dict(e) for e in meta["events"]],
            )
            textlog.unparsed.update(meta["unparsed"])
        return track, clock, textlog
