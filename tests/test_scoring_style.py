import pytest

from filmroom.contracts.models import Decision, Option, Sliders, StyleConfig
from filmroom.eval.labels import LabelRecord
from filmroom.eval.scoring import (
    DecisionPoint,
    final_action_predictions,
    label_decision_idx,
    random_expected,
    score,
    wilson_ci,
)
from filmroom.style import flip_reason, verdict


def _label(tp_frame: int | None, tp_pid: int | None = None) -> LabelRecord:
    return LabelRecord("P1", "tuning", "M", 0, 1000, None, tp_frame, tp_pid, None, None, None)


def test_wilson_ci_matches_known_values():
    lo, hi = wilson_ci(7, 10)
    assert lo == pytest.approx(0.3968, abs=1e-3)
    assert hi == pytest.approx(0.8922, abs=1e-3)
    assert wilson_ci(0, 0) == (0.0, 1.0)


def test_label_maps_to_nearest_decision_within_a_second():
    points = [DecisionPoint(100, 5), DecisionPoint(300, 7), DecisionPoint(500, 9)]
    assert label_decision_idx(_label(320), points) == 1
    assert label_decision_idx(_label(800), points) is None
    assert label_decision_idx(_label(None), points) is None


def test_label_breaks_distance_ties_by_player():
    points = [DecisionPoint(100, 5), DecisionPoint(200, 7)]
    assert label_decision_idx(_label(150, tp_pid=7), points) == 1


def test_exact_and_near_follow_the_matching_rule():
    truth = {"a": 3, "b": 3, "c": 3, "d": None}
    s = score("m", {"a": 3, "b": 4, "c": 1, "d": 2}, truth)
    assert (s.n, s.exact, s.near) == (3, 1, 2)


def test_final_action_baseline_picks_the_last_decision():
    assert final_action_predictions({"a": 5, "b": 0}) == {"a": 4, "b": None}


def test_random_baseline_equals_the_analytic_expectation():
    s = random_expected({"a": 0, "b": 2}, {"a": 4, "b": 5})
    assert s.exact == pytest.approx(1 / 4 + 1 / 5)
    assert s.near == pytest.approx(2 / 4 + 3 / 5)


def _style(sid: str, **weights: float) -> StyleConfig:
    sliders = Sliders(risk_tolerance=0.5, verticality=0.5, press_trigger=0.5, line_height=0.5)
    return StyleConfig(
        id=sid,
        name=sid,
        with_ball="possession",
        without_ball="mid_block",
        sliders=sliders,
        weights=weights,
        principles=[],
    )


def _option(oid: str, **factors: float) -> Option:
    return Option(
        id=oid,
        kind="pass",
        target_pid=None,
        target_xy=None,
        p_success=0.5,
        p_success_band="medium",
        danger_gain=0.0,
        factors=factors,
    )


DECISION = Decision(
    idx=0,
    frame=0,
    t_ms=0,
    pid=1,
    kind="pass",
    chosen_option_id="forward",
    options=[
        _option("forward", p_success=0.3, progression=0.9),
        _option("safe", p_success=0.9, progression=0.1),
    ],
    is_turning_point=True,
)


def test_verdict_picks_best_option_by_linear_score():
    safe_style = _style("safe", p_success=1.0, progression=0.2)
    v = verdict(DECISION, safe_style, safe_style)
    assert (v.best_option_id, v.better_available, v.flip_reason) == ("safe", True, None)
    assert v.margin == pytest.approx((0.9 + 0.02) - (0.3 + 0.18))


def test_flip_is_attributed_to_the_factor_contributing_most():
    safe_style = _style("safe", p_success=1.0, progression=0.2)
    direct = _style("direct", p_success=0.4, progression=1.5)
    reason = flip_reason(DECISION, safe_style, direct)
    assert reason.factor == "progression"
    assert reason.vs_style_id == "safe"
    assert reason.contribution == pytest.approx((1.5 - 0.2) * (0.9 - 0.1))
    assert flip_reason(DECISION, safe_style, safe_style) is None
