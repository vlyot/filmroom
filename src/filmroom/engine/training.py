"""Training rows and leave-one-match-out fits: every match is analysed with models that never saw it, so
live analysis can't draw on the current match's outcomes. Rows are cached per match; fitting is quick."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from filmroom.data.catalog import LOADER_VERSION, Catalog, MatchData
from filmroom.data.positions import team_of
from filmroom.data.textlog import Shot
from filmroom.engine import ENGINE_VERSION
from filmroom.engine.decisions import CARRY_LEAD_FRAMES, extract_decisions
from filmroom.engine.geometry import attacking, snapshot
from filmroom.engine.pass_model import (
    CARRY_FEATURES,
    PASS_FEATURES,
    EngineModels,
    SkillProfiles,
    carry_features,
    fit_logistic,
    pass_features,
)
from filmroom.engine.possessions import split_match
from filmroom.engine.shot_model import SHOT_FEATURES, shot_features


@dataclass(frozen=True)
class TrainingRows:
    pass_X: np.ndarray
    pass_y: np.ndarray
    pass_keys: list[str]
    carry_X: np.ndarray
    carry_y: np.ndarray  # True = the dribble kept the ball
    shot_X: np.ndarray
    shot_goal: np.ndarray
    shot_on_target: np.ndarray  # saved or scored

    @classmethod
    def concat(cls, parts: list["TrainingRows"]) -> "TrainingRows":
        return cls(
            np.concatenate([p.pass_X for p in parts]),
            np.concatenate([p.pass_y for p in parts]),
            [k for p in parts for k in p.pass_keys],
            np.concatenate([p.carry_X for p in parts]),
            np.concatenate([p.carry_y for p in parts]),
            np.concatenate([p.shot_X for p in parts]),
            np.concatenate([p.shot_goal for p in parts]),
            np.concatenate([p.shot_on_target for p in parts]),
        )


def training_rows(md: MatchData) -> TrainingRows:
    """One pass row per real pass attempt (failed ones aimed by reconstruction), one dribble row per spell on
    the ball, judged where a final dribble would be (kept unless it was a lost final dribble), and one shot
    row per real shot, judged where it was struck."""
    pass_x, pass_y, pass_keys, carry_x, carry_y = [], [], [], [], []
    for poss in split_match(md):
        view = md.until(poss.close_frame)
        decisions = extract_decisions(view, poss)
        for d in decisions:
            if d.kind == "pass" and d.target_xy is not None:
                snap = snapshot(view, d.frame, poss.team)
                pass_x.append(pass_features(snap, snap.position(d.pid), attacking(d.target_xy, poss.team)))
                pass_y.append(bool(d.completed))
                pass_keys.append(md.player(d.pid).key)
        lost_last = bool(decisions) and decisions[-1].kind == "carry"
        for i, spell in enumerate(poss.spells):
            snap = snapshot(view, max(spell.last_frame - CARRY_LEAD_FRAMES, spell.first_frame), poss.team)
            carry_x.append(carry_features(snap, snap.position(spell.pid)))
            carry_y.append(not (lost_last and i == len(poss.spells) - 1))
    shots = [e for e in md.events if isinstance(e, Shot)]
    shot_x = []
    for shot in shots:
        snap = snapshot(md, shot.start_frame, team_of(shot.pid))
        shot_x.append(shot_features(snap, snap.position(shot.pid)))
    return TrainingRows(
        np.asarray(pass_x, dtype=float).reshape(-1, len(PASS_FEATURES)),
        np.asarray(pass_y, dtype=bool),
        pass_keys,
        np.asarray(carry_x, dtype=float).reshape(-1, len(CARRY_FEATURES)),
        np.asarray(carry_y, dtype=bool),
        np.asarray(shot_x, dtype=float).reshape(-1, len(SHOT_FEATURES)),
        np.asarray([s.outcome == "goal" for s in shots], dtype=bool),
        np.asarray([s.outcome != "off_target" for s in shots], dtype=bool),
    )


def fit_models(rows: TrainingRows) -> EngineModels:
    passes = fit_logistic(rows.pass_X, rows.pass_y)
    skill = SkillProfiles.fit(rows.pass_keys, passes.predict(rows.pass_X), rows.pass_y)
    return EngineModels(
        passes,
        skill,
        fit_logistic(rows.carry_X, rows.carry_y),
        fit_logistic(rows.shot_X, rows.shot_goal),
        float(rows.shot_on_target.mean()),
    )


def fit_lomo(rows: dict[str, TrainingRows]) -> dict[str, EngineModels]:
    return {m: fit_models(TrainingRows.concat([r for k, r in rows.items() if k != m])) for m in rows}


def _rows_dir(cache_dir: Path) -> Path:
    return cache_dir / "engine" / f"rows-e{ENGINE_VERSION}-l{LOADER_VERSION}"


def load_rows(catalog: Catalog, cache_dir: Path) -> dict[str, TrainingRows]:
    """Training rows for every match with a usable event log, keyed by match ID."""
    out = {}
    for info in catalog.matches():
        path = _rows_dir(cache_dir) / f"{info.id}.npz"
        if path.exists():
            a = np.load(path)
            out[info.id] = TrainingRows(
                a["pass_X"],
                a["pass_y"],
                a["pass_keys"].tolist(),
                a["carry_X"],
                a["carry_y"],
                a["shot_X"],
                a["shot_goal"],
                a["shot_on_target"],
            )
            continue
        md = catalog.load(info.id)
        if not md.has_events:
            continue
        rows = training_rows(md)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, **{**rows.__dict__, "pass_keys": np.asarray(rows.pass_keys)})
        out[info.id] = rows
    return out
