"""Pitch geometry at one frame, always seen by the team in possession attacking towards x = 110."""

from dataclasses import dataclass

import numpy as np

from filmroom.data.catalog import MatchData
from filmroom.data.positions import BALL_PID

PITCH = np.asarray([110.0, 72.0])
CAP_M = 10.0  # distances beyond this carry no extra information for the models
CELL_M = 2.0
GRID = np.stack(
    np.meshgrid(np.arange(CELL_M / 2, PITCH[0], CELL_M), np.arange(CELL_M / 2, PITCH[1], CELL_M)), axis=-1
)


def attacking(xy: np.ndarray, team: int) -> np.ndarray:
    """Rotate pitch coordinates so `team` attacks towards x = 110; applying it twice gives the input back."""
    xy = np.asarray(xy, dtype=float)
    return xy if team == 0 else PITCH - xy


@dataclass(frozen=True)
class Snapshot:
    frame: int
    team: int
    ball: np.ndarray
    att_pids: np.ndarray
    att_xy: np.ndarray
    def_xy: np.ndarray

    def position(self, pid: int) -> np.ndarray:
        return self.att_xy[int(np.flatnonzero(self.att_pids == pid)[0])]


def snapshot(md: MatchData, frame: int, team: int) -> Snapshot:
    row = min(int(np.searchsorted(md.track.frames, frame)), len(md.track.frames) - 1)
    xy = attacking(md.track.xy[row], team)
    pids = md.track.pids
    present = ~np.isnan(xy[:, 0])
    players = present & (pids != BALL_PID)
    on_team = (pids > BALL_PID).astype(int) == team
    return Snapshot(
        frame=frame,
        team=team,
        ball=xy[pids == BALL_PID][0],
        att_pids=pids[players & on_team].astype(int),
        att_xy=xy[players & on_team],
        def_xy=xy[players & ~on_team],
    )


def _along(points: np.ndarray, origin: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Position along origin -> target (0 at origin, 1 at target) and distance from the line, per point."""
    d = target - origin
    t = (points - origin) @ d / max(float(d @ d), 1e-9)
    return t, np.linalg.norm(points - (origin + t[:, None] * d), axis=1)


def lane_clearance(snap: Snapshot, origin: np.ndarray, target: np.ndarray) -> float:
    """Nearest defender to the passing line, counting only defenders between passer and target."""
    t, dist = _along(snap.def_xy, origin, target)
    inside = (t > 0) & (t < 1)
    return min(CAP_M, float(dist[inside].min())) if inside.any() else CAP_M


def interceptors(snap: Snapshot, origin: np.ndarray, target: np.ndarray, radius: float = 2.0) -> int:
    t, dist = _along(snap.def_xy, origin, target)
    return int(((t > 0) & (t < 1) & (dist <= radius)).sum())


def nearest_defender(snap: Snapshot, xy: np.ndarray) -> float:
    return min(CAP_M, float(np.linalg.norm(snap.def_xy - xy, axis=1).min()))


def voronoi_control(snap: Snapshot) -> np.ndarray:
    """Distance-based pitch control on a 2 m grid: 1 where the nearest player is on the team in possession."""
    att = np.linalg.norm(GRID[:, :, None, :] - snap.att_xy, axis=-1).min(axis=-1)
    dfn = np.linalg.norm(GRID[:, :, None, :] - snap.def_xy, axis=-1).min(axis=-1)
    return (att < dfn).astype(float)


def space_share(control: np.ndarray, xy: np.ndarray, radius: float = 5.0) -> float:
    near = np.linalg.norm(GRID - xy, axis=-1) <= radius
    return float(control[near].mean()) if near.any() else 0.0
