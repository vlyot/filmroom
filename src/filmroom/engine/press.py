"""Press module: what losing the ball would cost, given how the team in possession is placed to defend it.

Counter-press cover is the space the team could deny straight away: teammates close to where the ball would
be lost. Rest defence is the space left behind: how much of the pitch between that spot and the team's own
goal it still controls. The press trigger and line-height sliders weight these, so the without-the-ball half
of a style judges on-ball choices through the transition they would lead to.
"""

import numpy as np

from filmroom.engine.geometry import CELL_M, GRID, Snapshot

COUNTER_PRESS_M = 10.0
COUNTER_PRESS_PLAYERS = 3


def counter_press(snap: Snapshot, loss_xy: np.ndarray) -> float:
    """Teammates within 10 m of where the ball would be lost, capped at three, scaled to [0, 1]."""
    near = int((np.linalg.norm(snap.att_xy - loss_xy, axis=1) <= COUNTER_PRESS_M).sum())
    return min(near, COUNTER_PRESS_PLAYERS) / COUNTER_PRESS_PLAYERS


def rest_defence(control: np.ndarray, loss_xy: np.ndarray) -> float:
    """Share of the pitch between the loss point and the team's own goal that the team in possession
    controls."""
    behind = GRID[..., 0] <= max(float(loss_xy[0]), CELL_M / 2)
    return float(control[behind].mean())
