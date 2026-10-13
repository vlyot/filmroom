"""Pass success, dribble and shot models: logistic regressions on the geometry at the moment of the decision,
plus a per-player skill offset for passes.

SoccER's game engine decides real outcomes, not these models, so their out-of-fold predictions can be checked
against real results without circularity.
"""

from dataclasses import dataclass, field

import numpy as np

from filmroom.contracts.models import Band
from filmroom.engine.geometry import Snapshot, interceptors, lane_clearance, nearest_defender

PASS_FEATURES = (
    "distance",
    "lane_clearance",
    "interceptors",
    "passer_pressure",
    "receiver_space",
    "forwardness",
)
CARRY_FEATURES = ("pressure", "defenders_ahead")
SKILL_PRIOR = 200  # pseudo-passes at league average per band; skill barely helps out-of-fold, so shrink hard
LOW_CONFIDENCE_N = 20
P_RANGE = (0.01, 0.99)
BAND_EDGES = (0.5, 0.8)


def band(p: float) -> Band:
    return "high" if p >= BAND_EDGES[1] else "medium" if p >= BAND_EDGES[0] else "low"


def pass_features(snap: Snapshot, origin: np.ndarray, target: np.ndarray) -> np.ndarray:
    return np.asarray(
        [
            float(np.linalg.norm(target - origin)),
            lane_clearance(snap, origin, target),
            interceptors(snap, origin, target),
            nearest_defender(snap, origin),
            nearest_defender(snap, target),
            float(target[0] - origin[0]),
        ]
    )


def carry_features(snap: Snapshot, origin: np.ndarray) -> np.ndarray:
    near = np.linalg.norm(snap.def_xy - origin, axis=1) <= 10.0
    ahead = near & (snap.def_xy[:, 0] > origin[0])
    return np.asarray([nearest_defender(snap, origin), float(ahead.sum())])


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return np.exp(-np.logaddexp(0.0, -z))


@dataclass(frozen=True)
class Logistic:
    mean: np.ndarray
    scale: np.ndarray
    weights: np.ndarray  # intercept first, then one per standardised feature

    def predict(self, X: np.ndarray) -> np.ndarray:
        return _sigmoid(self.weights[0] + ((X - self.mean) / self.scale) @ self.weights[1:])


def fit_logistic(X: np.ndarray, y: np.ndarray, l2: float = 1.0, iterations: int = 50) -> Logistic:
    """Ridge-penalised logistic regression by Newton's method (IRLS) on standardised features."""
    mean, scale = X.mean(axis=0), X.std(axis=0)
    scale[scale == 0] = 1.0
    Z = np.column_stack([np.ones(len(X)), (X - mean) / scale])
    penalty = np.full(Z.shape[1], l2)
    penalty[0] = 0.0
    w = np.zeros(Z.shape[1])
    for _ in range(iterations):
        p = _sigmoid(Z @ w)
        gradient = Z.T @ (y - p) - penalty * w
        hessian = (Z * (p * (1 - p))[:, None]).T @ Z + np.diag(penalty)
        step = np.linalg.solve(hessian, gradient)
        w += step
        if np.abs(step).max() < 1e-8:
            break
    return Logistic(mean, scale, w)


@dataclass(frozen=True)
class SkillProfiles:
    """Completions above expected per player and difficulty band (hard / medium / easy by the base model),
    shrunk towards zero for players with few passes."""

    edges: tuple[float, float]
    offsets: dict[str, list[float]] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)

    @classmethod
    def fit(cls, keys: list[str], base_p: np.ndarray, completed: np.ndarray) -> "SkillProfiles":
        edges = (float(np.quantile(base_p, 1 / 3)), float(np.quantile(base_p, 2 / 3)))
        bands = np.searchsorted(edges, base_p, side="right")
        residual = completed.astype(float) - base_p
        keys_arr = np.asarray(keys)
        offsets, counts = {}, {}
        for key in sorted(set(keys)):
            mine = keys_arr == key
            offsets[key] = [
                float(residual[mine & (bands == b)].sum() / ((mine & (bands == b)).sum() + SKILL_PRIOR))
                for b in range(3)
            ]
            counts[key] = int(mine.sum())
        return cls(edges, offsets, counts)

    def offset(self, keys: list[str], base_p: np.ndarray) -> np.ndarray:
        bands = np.searchsorted(self.edges, base_p, side="right")
        return np.asarray([self.offsets.get(k, [0.0, 0.0, 0.0])[b] for k, b in zip(keys, bands, strict=True)])

    def low_confidence(self, key: str) -> bool:
        return self.counts.get(key, 0) < LOW_CONFIDENCE_N


@dataclass(frozen=True)
class EngineModels:
    passes: Logistic
    skill: SkillProfiles
    carry: Logistic
    shot_goal: Logistic  # xG
    on_target_rate: float  # where a shot is taken barely changes whether it hits the target, so one rate

    def pass_p(self, X: np.ndarray, keys: list[str]) -> np.ndarray:
        base = self.passes.predict(X)
        return np.clip(base + self.skill.offset(keys, base), *P_RANGE)

    def carry_p(self, X: np.ndarray) -> np.ndarray:
        return np.clip(self.carry.predict(X), *P_RANGE)

    def xg(self, X: np.ndarray) -> np.ndarray:
        return np.clip(self.shot_goal.predict(X), *P_RANGE)
