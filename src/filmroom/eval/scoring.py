"""Turning-point scoring. A label's turning point is mapped to the nearest decision; a prediction matches
exactly if it picks that decision, and nearly if it is within one decision of it."""

import math
from dataclasses import dataclass

from filmroom.eval.labels import LabelRecord

TOLERANCE_FRAMES = 100  # ~1 s at 100 Hz; labels are timed to the second


@dataclass(frozen=True)
class DecisionPoint:
    frame: int
    pid: int


@dataclass(frozen=True)
class Score:
    method: str
    n: int
    exact: float
    near: float

    @property
    def exact_ci(self) -> tuple[float, float]:
        return wilson_ci(self.exact, self.n)

    @property
    def near_ci(self) -> tuple[float, float]:
        return wilson_ci(self.near, self.n)


def wilson_ci(k: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def label_decision_idx(label: LabelRecord, decisions: list[DecisionPoint]) -> int | None:
    """The labelled player's nearest decision within the tolerance, else the nearest decision by anyone.
    Labels are timed to the whole second but name the player, so the player is the stronger signal."""
    if label.tp_frame is None:
        return None
    in_range = [i for i, d in enumerate(decisions) if abs(d.frame - label.tp_frame) <= TOLERANCE_FRAMES]
    if not in_range:
        return None
    return min(
        in_range, key=lambda i: (decisions[i].pid != label.tp_pid, abs(decisions[i].frame - label.tp_frame))
    )


def score(method: str, predictions: dict[str, int | None], truth: dict[str, int | None]) -> Score:
    scored = {k: t for k, t in truth.items() if t is not None}
    exact = sum(predictions.get(k) == t for k, t in scored.items())
    near = sum(predictions.get(k) is not None and abs(predictions[k] - t) <= 1 for k, t in scored.items())
    return Score(method, len(scored), exact, near)


def final_action_predictions(n_decisions: dict[str, int]) -> dict[str, int | None]:
    return {k: n - 1 if n else None for k, n in n_decisions.items()}


def random_expected(truth: dict[str, int | None], n_decisions: dict[str, int]) -> Score:
    """Expected score of picking a decision uniformly at random, computed exactly rather than sampled."""
    scored = {k: t for k, t in truth.items() if t is not None and n_decisions.get(k)}
    exact = sum(1 / n_decisions[k] for k in scored)
    near = sum(
        len({max(0, t - 1), t, min(n_decisions[k] - 1, t + 1)}) / n_decisions[k] for k, t in scored.items()
    )
    return Score("random (expected)", len(scored), exact, near)
