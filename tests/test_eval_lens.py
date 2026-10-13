from filmroom.engine.analyse import analyse_match
from filmroom.engine.turning_point import EngineParams
from filmroom.eval.lens import (
    attribution,
    direction_violations,
    disagreement,
    flag_rates,
    flagged_turning_points,
)
from filmroom.style import load_lens
from tests.engine_synth import counter_attack
from tests.test_engine_analysis import FLAG_ALL, STYLES, constant_models


def _analyses():
    return analyse_match(counter_attack().build(), constant_models(), STYLES, FLAG_ALL)


def test_flags_are_recomputed_from_regret_under_the_given_params():
    analyses = _analyses()
    assert len(flagged_turning_points(analyses, FLAG_ALL)) == sum(a.possession.flagged for a in analyses)
    assert flagged_turning_points(analyses, EngineParams(flag_threshold=10.0, severity_scale=1.0)) == []


def test_lens_checks_cover_every_preset_pair_and_slider():
    decisions = flagged_turning_points(_analyses(), FLAG_ALL)
    pairs = disagreement(decisions, STYLES)
    assert len(pairs) == 15 and all(p.n == len(decisions) for p in pairs)
    attributed = attribution(decisions, STYLES)
    assert attributed.failures == [] and attributed.rate == 1.0
    assert direction_violations(decisions, load_lens(), STYLES) == {s.slider: 0 for s in load_lens().sliders}


def test_flag_rates_split_by_final_action_and_add_up():
    rates = flag_rates(_analyses(), FLAG_ALL)
    assert rates["all"][1] == sum(rates[k][1] for k in ("pass", "shot", "carry"))
    assert rates["all"][0] == sum(rates[k][0] for k in ("pass", "shot", "carry"))
