import numpy as np
import pytest

from filmroom.engine.decisions import RawDecision
from filmroom.engine.geometry import Snapshot
from filmroom.engine.options import candidate_options
from filmroom.engine.pass_model import Logistic
from filmroom.engine.shot_model import blockers, goal_angle, shot_features
from filmroom.engine.training import training_rows
from filmroom.style import load_lens, presets, score
from tests.engine_synth import SynthMatch
from tests.test_engine_analysis import constant, constant_models

PRESETS = presets(load_lens())
# A plausible xG model on (distance, angle, blockers): closer, wider and clearer shots go in more often.
XG = Logistic(np.zeros(3), np.ones(3), np.asarray([1.0, -0.15, 1.0, -0.5]))


def _models():
    return constant_models(shots=XG)


def _snapshot(
    shooter: tuple[float, float], mate: tuple[float, float], dfn: list[tuple[float, float]]
) -> Snapshot:
    att = np.asarray([shooter, mate], dtype=float)
    return Snapshot(0, 0, att[0], np.asarray([1, 2]), att, np.asarray(dfn, dtype=float))


def _best(snap: Snapshot, style) -> str:
    options = [c.option for c in candidate_options(snap, RawDecision(0, 1, "shot"), 0, _models(), "k")]
    return max(options, key=lambda o: score(o, style)).id


def test_closer_and_more_central_shots_see_a_wider_goal():
    assert goal_angle(np.asarray((100.0, 36.0))) > goal_angle(np.asarray((80.0, 36.0)))
    assert goal_angle(np.asarray((100.0, 36.0))) > goal_angle(np.asarray((100.0, 10.0)))


def test_only_defenders_inside_the_shooting_triangle_count_as_blockers():
    snap = _snapshot((90, 36), (80, 20), [(100, 36), (109, 37), (100, 50), (85, 36)])
    assert blockers(snap, np.asarray((90.0, 36.0))) == 2
    assert shot_features(snap, np.asarray((90.0, 36.0)))[2] == 2


def test_training_rows_hold_one_row_per_real_shot_with_its_outcome():
    md = (
        SynthMatch().hold(9, 30).shot(9, outcome="saved").hold(9, 30).shot(9, outcome="goal").idle(50).build()
    )
    rows = training_rows(md)
    assert rows.shot_X.shape == (2, 3)
    assert rows.shot_goal.tolist() == [False, True] and rows.shot_on_target.tolist() == [True, True]


def test_the_shot_option_is_worth_its_xg_and_succeeds_at_the_on_target_rate():
    snap = _snapshot((95, 36), (80, 20), [(109, 36)])
    models = constant_models(shots=constant(0.25, 3))
    options = candidate_options(snap, RawDecision(0, 1, "shot"), 3, models, "k")
    [shot] = [c for c in options if c.option.kind == "shot"]
    assert shot.option.id == "d3.shot" and shot.value == pytest.approx(0.25)
    assert shot.option.p_success == 0.5 and shot.option.target_xy == (110.0, 36.0)


def test_a_shot_is_weighed_against_passes_only():
    snap = _snapshot((95, 36), (80, 20), [(109, 36)])
    kinds = [c.option.kind for c in candidate_options(snap, RawDecision(0, 1, "shot"), 0, _models(), "k")]
    assert kinds == ["pass", "shot"]
    passing = [
        c.option.kind for c in candidate_options(snap, RawDecision(0, 1, "pass", True, 2), 0, _models(), "k")
    ]
    assert passing == ["pass", "carry"]


def test_a_clear_chance_close_to_goal_is_the_best_option_under_every_preset():
    snap = _snapshot((104, 36), (90, 20), [(109, 36), (80, 60)])
    assert {_best(snap, style) for style in PRESETS} == {"d0.shot"}


def test_a_long_blocked_shot_never_beats_a_safe_forward_pass():
    snap = _snapshot((75, 36), (90, 36), [(109, 36), (95, 33), (95, 39), (60, 60)])
    assert "d0.shot" not in {_best(snap, style) for style in PRESETS}
