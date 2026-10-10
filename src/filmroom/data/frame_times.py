from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FrameClock:
    frames: np.ndarray
    ms: np.ndarray

    @classmethod
    def from_csv(cls, path: Path) -> "FrameClock":
        df = pd.read_csv(path, dtype={"frame": np.int32, "game_ms": np.int64})
        return cls(df["frame"].to_numpy(), df["game_ms"].to_numpy())

    def ms_of(self, frames: np.ndarray) -> np.ndarray:
        idx = np.clip(np.searchsorted(self.frames, frames), 0, len(self.frames) - 1)
        return self.ms[idx]

    def ms_at(self, frame: int) -> int:
        return int(self.ms_of(np.asarray([frame]))[0])

    def frame_at(self, ms: int) -> int:
        """First frame at or after the given game time."""
        idx = min(int(np.searchsorted(self.ms, ms, side="left")), len(self.ms) - 1)
        return int(self.frames[idx])
