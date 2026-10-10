from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from filmroom.data.frame_times import FrameClock

BALL_PID = 128


@dataclass(frozen=True)
class PositionTrack:
    frames: np.ndarray  # (n,) int32
    pids: np.ndarray  # (23,) ball, then team 0, then team 1
    xy: np.ndarray  # (n, 23, 2) float32; NaN where an entity has no row for that frame

    @property
    def missing(self) -> int:
        return int(np.isnan(self.xy[..., 0]).sum())

    def take(self, idx: np.ndarray) -> "PositionTrack":
        return PositionTrack(self.frames[idx], self.pids, self.xy[idx])

    def window(self, start_frame: int, end_frame: int) -> "PositionTrack":
        lo, hi = np.searchsorted(self.frames, [start_frame, end_frame + 1])
        return self.take(np.arange(lo, hi))


def entity_order(pids: np.ndarray) -> np.ndarray:
    pids = np.unique(pids)
    return np.concatenate([pids[pids == BALL_PID], pids[pids < BALL_PID], pids[pids > BALL_PID]])


def parse_positions(path: Path) -> PositionTrack:
    df = pd.read_csv(
        path,
        sep=" ",
        header=None,
        names=["frame", "pid", "x", "y"],
        dtype={"frame": np.int32, "pid": np.int16, "x": np.float32, "y": np.float32},
    )
    frame_col, pid_col = df["frame"].to_numpy(), df["pid"].to_numpy()
    frames = np.unique(frame_col)
    pids = entity_order(pid_col)
    slot = np.zeros(int(pids.max()) + 1, dtype=np.int16)
    slot[pids] = np.arange(len(pids))
    xy = np.full((len(frames), len(pids), 2), np.nan, dtype=np.float32)
    xy[np.searchsorted(frames, frame_col), slot[pid_col]] = df[["x", "y"]].to_numpy()
    return PositionTrack(frames, pids, xy)


def downsample(track: PositionTrack, clock: FrameClock, hz: int = 10) -> PositionTrack:
    """Keep the frame nearest each 1000/hz ms step of game time."""
    ms = clock.ms_of(track.frames)
    targets = np.arange(ms[0], ms[-1] + 1, 1000 / hz)
    right = np.clip(np.searchsorted(ms, targets), 1, len(ms) - 1)
    left_closer = (targets - ms[right - 1]) <= (ms[right] - targets)
    return track.take(np.unique(np.where(left_closer, right - 1, right)))
