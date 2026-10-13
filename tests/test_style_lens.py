import itertools
from collections import Counter
from typing import get_args

import numpy as np
import pytest

from filmroom.contracts.models import Decision, FactorName, Option, SliderName, Sliders
from filmroom.style import (
    flip_reason,
    load_lens,
    presets,
    public_lens,
    score,
    style_from_sliders,
    weights_from_sliders,
)

LENS = load_lens()
PRESETS = presets(LENS)
FACTORS: tuple[FactorName, ...] = get_args(FactorName)
SLIDERS: tuple[SliderName, ...] = get_args(SliderName)


def _option(oid: str, factors: dict[str, float]) -> Option:
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


def _random_factors(rng: np.random.Generator) -> dict[str, float]:
    return {f: float(v) for f, v in zip(FACTORS, rng.random(len(FACTORS)), strict=True)}


def test_every_preset_takes_its_weights_from_its_two_rule_sets():
    for p in PRESETS:
        rule_sliders = LENS.rule_set(p.with_ball).sliders | LENS.rule_set(p.without_ball).sliders
        assert p.sliders.model_dump() == rule_sliders
        assert p.weights == weights_from_sliders(LENS, p.sliders)


def test_weights_cover_every_factor_and_stay_non_negative_across_the_slider_range():
    assert set(LENS.base) == set(FACTORS)
    for corner in itertools.product((0.0, 1.0), repeat=len(SLIDERS)):
        weights = weights_from_sliders(LENS, Sliders(**dict(zip(SLIDERS, corner, strict=True))))
        assert min(weights.values()) >= 0


def test_each_factor_is_moved_by_at_most_one_slider():
    owners = Counter(f for spec in LENS.sliders for f in spec.gains)
    assert max(owners.values()) == 1
    assert [spec.slider for spec in LENS.sliders] == list(SLIDERS)


def test_every_pair_of_presets_differs_on_a_slider():
    for a, b in itertools.combinations(PRESETS, 2):
        assert a.sliders != b.sliders, (a.id, b.id)


def test_every_weight_difference_between_presets_is_named_on_both_cards():
    for a, b in itertools.combinations(PRESETS, 2):
        for factor in FACTORS:
            if a.weights[factor] != b.weights[factor]:
                assert factor in {p.factor for p in a.principles}, (a.id, factor)
                assert factor in {p.factor for p in b.principles}, (b.id, factor)


def test_the_reference_comes_first_and_preset_ids_stay_stable():
    ids = [p.id for p in PRESETS]
    assert ids[0] == "possession-high-press" and "counter-low-block" in ids
    assert len(ids) == len(set(ids)) == 6
    assert public_lens(LENS).reference_style_id == ids[0]
    axes = Counter(r.axis for r in LENS.rule_sets)
    assert axes == {"with_ball": 3, "without_ball": 3}


def test_a_custom_style_carries_the_principles_of_its_rule_sets():
    sliders = Sliders(risk_tolerance=0.4, verticality=0.6, press_trigger=0.3, line_height=0.7)
    custom = style_from_sliders(LENS, "direct", "low_block", sliders)
    assert custom.id == "custom" and custom.weights == weights_from_sliders(LENS, sliders)
    assert custom.principles == LENS.rule_set("direct").principles + LENS.rule_set("low_block").principles


@pytest.mark.parametrize("spec", LENS.sliders, ids=lambda s: s.slider)
def test_raising_a_slider_only_moves_rankings_in_its_stated_direction(spec):
    """For pairs where o1 is at least as good as o2 on every factor the slider moves (in the direction of its
    gain), sweeping the slider upward never drops o1 below o2 once it is level or ahead."""
    rng = np.random.default_rng(7)
    positions = np.linspace(0, 1, 11)
    for _ in range(500):
        f1, f2 = _random_factors(rng), _random_factors(rng)
        for factor, gain in spec.gains.items():
            if np.sign(gain) * (f1[factor] - f2[factor]) < 0:
                f1[factor], f2[factor] = f2[factor], f1[factor]
        o1, o2 = _option("o1", f1), _option("o2", f2)
        start = dict(zip(SLIDERS, rng.random(len(SLIDERS)), strict=True))
        ahead = []
        for x in positions:
            style = style_from_sliders(LENS, "possession", "mid_block", Sliders(**(start | {spec.slider: x})))
            ahead.append(score(o1, style) >= score(o2, style) - 1e-9)
        assert ahead == sorted(ahead), spec.slider


def test_every_flip_between_presets_is_attributed_to_a_named_factor_with_a_positive_share():
    rng = np.random.default_rng(11)
    flips = 0
    for _ in range(300):
        options = [_option(f"o{i}", _random_factors(rng)) for i in range(4)]
        decision = Decision(
            idx=0,
            frame=0,
            t_ms=0,
            pid=1,
            kind="pass",
            chosen_option_id="o0",
            options=options,
            is_turning_point=True,
        )
        for a, b in itertools.permutations(PRESETS, 2):
            reason = flip_reason(decision, a, b)
            if reason is None:
                continue
            flips += 1
            assert reason.contribution > 0 and a.weights[reason.factor] != b.weights[reason.factor]
            assert reason.factor in {p.factor for p in a.principles + b.principles}
    assert flips > 0
