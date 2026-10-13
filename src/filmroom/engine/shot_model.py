"""Shot geometry for the xG model: a logistic regression on these features, fitted leave one match out on real
SoccER shots in training.py. The game engine decides those outcomes, not our model, so it can be checked
against them. Whether a shot hits the target barely depends on this geometry in SoccER (a logistic on it
scored no better than the base rate out of fold), so a shot's chance of hitting the target is one rate.
"""

import numpy as np

from filmroom.engine.geometry import PITCH, Snapshot

GOAL_WIDTH_M = 7.32
POSTS = np.asarray([(PITCH[0], (PITCH[1] - GOAL_WIDTH_M) / 2), (PITCH[0], (PITCH[1] + GOAL_WIDTH_M) / 2)])
SHOT_FEATURES = ("distance", "angle", "blockers")


def goal_angle(origin: np.ndarray) -> float:
    """Angle between the two posts as seen from the shooter, in radians."""
    a, b = POSTS[0] - origin, POSTS[1] - origin
    return float(np.arctan2(abs(a[0] * b[1] - a[1] * b[0]), a @ b))


def blockers(snap: Snapshot, origin: np.ndarray) -> int:
    """Defenders (the goalkeeper included) inside the triangle between the shooter and the posts."""
    p, a, b = snap.def_xy, POSTS[0], POSTS[1]

    def side(u: np.ndarray, v: np.ndarray) -> np.ndarray:
        return (v[0] - u[0]) * (p[:, 1] - u[1]) - (v[1] - u[1]) * (p[:, 0] - u[0])

    s1, s2, s3 = side(origin, a), side(a, b), side(b, origin)
    inside = ((s1 >= 0) & (s2 >= 0) & (s3 >= 0)) | ((s1 <= 0) & (s2 <= 0) & (s3 <= 0))
    return int(inside.sum())


def shot_features(snap: Snapshot, origin: np.ndarray) -> np.ndarray:
    centre = POSTS.mean(axis=0)
    return np.asarray([float(np.linalg.norm(centre - origin)), goal_angle(origin), blockers(snap, origin)])
