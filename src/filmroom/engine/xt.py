"""Expected threat (xT): how likely play from a spot ends in a goal, from Karun Singh's published 12 x 8 grid
(source in xt_12x8.json), stretched over SoccER's 110 x 72 pitch."""

import json
from pathlib import Path

import numpy as np

from filmroom.contracts.models import DangerPoint
from filmroom.data.catalog import MatchData
from filmroom.data.positions import downsample
from filmroom.engine.geometry import PITCH, attacking
from filmroom.engine.possessions import RawPossession

GRID = np.asarray(json.loads(Path(__file__).with_name("xt_12x8.json").read_text(encoding="utf-8"))["grid"])


def xt(xy: np.ndarray) -> np.ndarray:
    """xT at points already rotated so the team in possession attacks towards x = 110."""
    xy = np.asarray(xy, dtype=float)
    col = np.clip((xy[..., 0] / PITCH[0] * GRID.shape[1]).astype(int), 0, GRID.shape[1] - 1)
    row = np.clip((xy[..., 1] / PITCH[1] * GRID.shape[0]).astype(int), 0, GRID.shape[0] - 1)
    return GRID[row, col]


def danger_curve(md: MatchData, poss: RawPossession, hz: int = 2) -> list[DangerPoint]:
    samples = downsample(md.track.window(poss.start_frame, poss.end_frame), md.clock, hz)
    values = xt(attacking(samples.xy[:, 0], poss.team))
    return [
        DangerPoint(t_ms=md.clock.ms_at(int(f)), xt=round(float(v), 4))
        for f, v in zip(samples.frames, values, strict=True)
    ]
