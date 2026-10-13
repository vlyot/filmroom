"""Candidate options at a decision and what each is worth.

A pass is worth p * [k * xT(destination) - (1 - k) * the opponent's xT there] - (1 - p) * the opponent's
xT where it would be cut out, where k is the chance the receiver keeps the ball (the dribble model at the
receiver's spot): a completed pass into pressure is still a poor pass. A dribble is judged where it goes, like
a pass: k * xT(destination) - (1 - k) * the opponent's xT there, with k the dribble model at the destination;
the chosen dribble goes where the player went, any other one 5 m towards goal. A shot is worth its xG and is
weighed against passes only: the dribble model learned from spells that mostly end in a pass and rates
carrying on into the box as safe, which made "dribble on" beat most shots. Danger gain is value minus xT where
the ball is now. Style factors are fixed-scale transforms into [0, 1], so the browser can re-score offline
with the same linear sum; the press factors are read at the spot the ball would be lost.
"""

from dataclasses import dataclass

import numpy as np

from filmroom.contracts.models import ActionKind, FactorName, Option
from filmroom.engine.decisions import RawDecision
from filmroom.engine.geometry import PITCH, Snapshot, attacking, lane_clearance, space_share, voronoi_control
from filmroom.engine.pass_model import EngineModels, band, carry_features, pass_features
from filmroom.engine.press import counter_press, rest_defence
from filmroom.engine.shot_model import POSTS, blockers, shot_features
from filmroom.engine.xt import xt

CARRY_M = 5.0
CARRY_MIN_M = 1.0  # a knock-on collected on the spot has no direction of its own
DANGER_SCALE = 0.1
PROGRESSION_M = 30.0
LANE_M = 5.0
SWITCH_M = 40.0
SWITCH_MIN_M = 15.0
BLOCKERS_CLOSED = 3  # the goalkeeper and two defenders in the shooting triangle leave no lane


@dataclass(frozen=True)
class Candidate:
    option: Option
    value: float


def chosen_option_id(decision: RawDecision, idx: int) -> str:
    if decision.kind != "pass":
        return f"d{idx}.{decision.kind}"
    return f"d{idx}.pass.{decision.target_pid if decision.target_pid is not None else 'space'}"


def _switch_of_play(snap: Snapshot, origin: np.ndarray, dest: np.ndarray) -> float:
    """Credit for moving the ball a long way across into the half with fewer defenders."""
    half = PITCH[1] / 2

    def defenders_on_side(y: float) -> int:
        return int(((snap.def_xy[:, 1] >= half) == (y >= half)).sum())

    dy = abs(float(dest[1] - origin[1]))
    if dy < SWITCH_MIN_M or defenders_on_side(dest[1]) >= defenders_on_side(origin[1]):
        return 0.0
    return min(1.0, dy / SWITCH_M)


def _carry_destination(snap: Snapshot, decision: RawDecision, origin: np.ndarray) -> np.ndarray:
    if decision.kind == "carry" and decision.target_xy is not None:
        went_to = attacking(decision.target_xy, snap.team)
        if np.linalg.norm(went_to - origin) >= CARRY_MIN_M:
            return went_to
    return np.clip(origin + (CARRY_M, 0.0), 0, PITCH)


@dataclass(frozen=True)
class _Context:
    snap: Snapshot
    origin: np.ndarray
    control: np.ndarray

    def candidate(
        self,
        oid: str,
        kind: ActionKind,
        target_pid: int | None,
        p: float,
        value: float,
        shown_at: np.ndarray,
        lost_at: np.ndarray,
        shape: dict[FactorName, float],
    ) -> Candidate:
        gain = value - float(xt(self.origin))
        factors: dict[FactorName, float] = {
            "p_success": p,
            "danger_gain": float(np.clip(gain / DANGER_SCALE, 0, 1)),
            **shape,
            "counter_press": counter_press(self.snap, lost_at),
            "rest_defence": rest_defence(self.control, lost_at),
        }
        pitch_xy = attacking(shown_at, self.snap.team)
        option = Option(
            id=oid,
            kind=kind,
            target_pid=target_pid,
            target_xy=(round(float(pitch_xy[0]), 2), round(float(pitch_xy[1]), 2)),
            p_success=round(p, 3),
            p_success_band=band(p),
            danger_gain=round(gain, 4),
            factors={k: round(v, 3) for k, v in factors.items()},
        )
        return Candidate(option, value)

    def move(
        self,
        oid: str,
        kind: ActionKind,
        target_pid: int | None,
        p: float,
        dest: np.ndarray,
        lost_at: np.ndarray,
        keep: float = 1.0,
    ) -> Candidate:
        """A pass or a dribble to `dest`, which fails at `lost_at` with probability 1 - p."""
        arrived = keep * xt(dest) - (1 - keep) * xt(PITCH - dest)
        value = float(p * arrived - (1 - p) * xt(PITCH - lost_at))
        shape: dict[FactorName, float] = {
            "progression": float(np.clip((dest[0] - self.origin[0]) / PROGRESSION_M, 0, 1)),
            "receiver_space": space_share(self.control, dest),
            "lane_openness": min(1.0, lane_clearance(self.snap, self.origin, dest) / LANE_M),
            "switch_of_play": _switch_of_play(self.snap, self.origin, dest),
        }
        return self.candidate(oid, kind, target_pid, p, value, dest, lost_at, shape)

    def shot(self, oid: str, models: EngineModels) -> Candidate:
        """Worth its xG; it succeeds when it hits the target, and its lane is how clear the shooting triangle
        is. It gains no ground for a teammate and switches nothing."""
        features = shot_features(self.snap, self.origin)[None, :]
        shape: dict[FactorName, float] = {
            "progression": 0.0,
            "receiver_space": space_share(self.control, self.origin),
            "lane_openness": 1 - min(blockers(self.snap, self.origin), BLOCKERS_CLOSED) / BLOCKERS_CLOSED,
            "switch_of_play": 0.0,
        }
        xg = float(models.xg(features)[0])
        return self.candidate(
            oid, "shot", None, models.on_target_rate, xg, POSTS.mean(axis=0), self.origin, shape
        )


def candidate_options(
    snap: Snapshot, decision: RawDecision, idx: int, models: EngineModels, passer_key: str
) -> list[Candidate]:
    """Passes to every teammate, plus the shot at a shot decision or one dribble otherwise. The chosen action
    is one of them; a pass into space gets an option of its own."""
    origin = snap.position(decision.pid)
    ctx = _Context(snap, origin, voronoi_control(snap))
    targets = [
        (f"d{idx}.pass.{pid}", int(pid), xy) for pid, xy in zip(snap.att_pids, snap.att_xy, strict=True)
    ]
    targets = [t for t in targets if t[1] != decision.pid]
    if decision.kind == "pass" and decision.target_pid is None:
        targets.append((f"d{idx}.pass.space", None, attacking(decision.target_xy, snap.team)))
    features = np.stack([pass_features(snap, origin, dest) for _, _, dest in targets])
    p_pass = models.pass_p(features, [passer_key] * len(targets))
    p_keep = models.carry_p(np.stack([carry_features(snap, dest) for _, _, dest in targets]))
    candidates = [
        ctx.move(oid, "pass", pid, float(p), dest, (origin + dest) / 2, float(k))
        for (oid, pid, dest), p, k in zip(targets, p_pass, p_keep, strict=True)
    ]
    if decision.kind == "shot":
        return [*candidates, ctx.shot(f"d{idx}.shot", models)]
    carry_to = _carry_destination(snap, decision, origin)
    p_carry = float(models.carry_p(carry_features(snap, carry_to)[None, :])[0])
    return [*candidates, ctx.move(f"d{idx}.carry", "carry", None, p_carry, carry_to, carry_to)]
