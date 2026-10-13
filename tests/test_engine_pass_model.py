import numpy as np
import pytest

from filmroom.engine.pass_model import SkillProfiles, band, fit_logistic
from filmroom.engine.training import TrainingRows, fit_lomo, fit_models, training_rows
from filmroom.eval.calibration import calibration_report
from tests.engine_synth import counter_attack


def test_irls_recovers_known_coefficients():
    rng = np.random.default_rng(7)
    X = rng.normal(size=(20000, 2))
    p = 1 / (1 + np.exp(-(0.5 + 1.5 * X[:, 0] - 0.8 * X[:, 1])))
    model = fit_logistic(X, rng.random(20000) < p, l2=0.0)
    assert np.allclose(model.weights, [0.5, 1.5, -0.8], atol=0.08)
    assert np.allclose(model.predict(X[:5]), p[:5], atol=0.03)


def test_skill_offsets_shrink_small_samples_towards_zero():
    keys = ["few"] * 5 + ["many"] * 3000
    base = np.full(len(keys), 0.5)
    completed = np.ones(len(keys), dtype=bool)
    skill = SkillProfiles.fit(keys, base, completed)
    few, many = skill.offset(["few", "many"], np.asarray([0.5, 0.5]))
    assert 0 < few < 0.05 < many < 0.5
    assert skill.low_confidence("few") and not skill.low_confidence("many")


def _rows(seed: int, n: int = 400) -> TrainingRows:
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, 6))
    goal = rng.random(n) < 0.1 + 0.05 * seed
    return TrainingRows(
        X, rng.random(n) < 0.5 + 0.1 * seed, ["k"] * n, X[:, :2], rng.random(n) < 0.8, X[:, :3], goal, goal
    )


def test_leave_one_match_out_never_trains_on_the_held_out_match():
    rows = {"A": _rows(0), "B": _rows(1), "C": _rows(2)}
    models = fit_lomo(rows)
    expected = fit_models(TrainingRows.concat([rows["B"], rows["C"]]))
    assert np.allclose(models["A"].passes.weights, expected.passes.weights)
    assert np.allclose(models["A"].shot_goal.weights, expected.shot_goal.weights)
    assert not np.allclose(models["A"].passes.weights, models["B"].passes.weights)


def test_training_rows_cover_every_pass_attempt_and_spell_on_the_ball():
    rows = training_rows(counter_attack().build())
    assert rows.pass_y.tolist() == [True, True, False, True, True]
    assert rows.pass_keys == ["p6", "p9", "p10", "p151", "p5"]
    assert rows.carry_y.tolist() == [True, True, True, True, False, True, True]


def test_bands_and_calibration_report():
    assert [band(p) for p in (0.49, 0.5, 0.79, 0.8)] == ["low", "medium", "medium", "high"]
    p = np.asarray([0.1, 0.1, 0.9, 0.9])
    report = calibration_report(p, np.asarray([0.0, 0.0, 1.0, 1.0]))
    assert report.n == 4 and report.ece == pytest.approx(0.1)
    assert report.bands["low"].n == 2 and report.bands["high"].observed == 1.0
