import math
from typing import get_args

import numpy as np
import pytest

from filmroom.contracts.models import FactorName, Possession
from filmroom.engine.analyse import analyse_match, analyse_possession
from filmroom.engine.decisions import RawDecision
from filmroom.engine.geometry import PITCH, Snapshot
from filmroom.engine.options import Candidate, candidate_options, chosen_option_id
from filmroom.engine.pass_model import EngineModels, Logistic, SkillProfiles
from filmroom.engine.possessions import PossessionSplitter
from filmroom.engine.turning_point import EngineParams, fit_params, regret
from filmroom.engine.xt import xt
from filmroom.style import load_lens, presets
from tests.engine_synth import SynthMatch, counter_attack

STYLES = presets(load_lens())
FLAG_ALL = EngineParams(flag_threshold=0.0, severity_scale=0.05)


def constant(p: float, n: int) -> Logistic:
    return Logistic(np.zeros(n), np.ones(n), np.asarray([math.log(p / (1 - p)), *([0.0] * n)]))


def constant_models(
    p_pass: float = 0.8, p_carry: float = 0.7, carry: Logistic | None = None, shots: Logistic | None = None
) -> EngineModels:
    return EngineModels(
        constant(p_pass, 6),
        SkillProfiles((0.5, 0.5)),
        carry or constant(p_carry, 2),
        shots or constant(0.1, 3),
        0.5,
    )


def _snapshot() -> Snapshot:
    att = np.asarray([(50.0, 36.0), (70.0, 36.0), (60.0, 60.0)])
    return Snapshot(0, 0, att[0], np.asarray([1, 2, 3]), att, np.asarray([(60.0, 30.0), (90.0, 36.0)]))


def test_chosen_action_is_one_of_the_candidates_with_unique_ids():
    snap = _snapshot()
    for decision in (
        RawDecision(0, 1, "pass", True, 2, (70.0, 36.0)),
        RawDecision(0, 1, "pass", False, None, (80.0, 10.0)),
        RawDecision(0, 1, "shot"),
        RawDecision(0, 1, "carry"),
    ):
        ids = [c.option.id for c in candidate_options(snap, decision, 4, constant_models(), "k")]
        assert len(ids) == len(set(ids))
        assert chosen_option_id(decision, 4) in ids


def test_pass_value_counts_losing_the_ball_on_the_way_and_after_it_arrives():
    snap = _snapshot()
    by_id = {
        c.option.id: c
        for c in candidate_options(
            snap, RawDecision(0, 1, "pass", True, 2, (70.0, 36.0)), 0, constant_models(), "k"
        )
    }
    origin, dest = np.asarray((50.0, 36.0)), np.asarray((70.0, 36.0))
    arrived = 0.7 * xt(dest) - 0.3 * xt(PITCH - dest)  # the receiver keeps it 70% of the time
    expected = 0.8 * arrived - 0.2 * xt(PITCH - (origin + dest) / 2)
    forward = by_id["d0.pass.2"]
    assert forward.value == pytest.approx(expected)
    assert forward.option.danger_gain == round(expected - xt(origin), 4)
    assert forward.option.p_success_band == "high" and by_id["d0.carry"].option.p_success == 0.7


def test_every_option_carries_all_eight_factors_in_the_unit_interval():
    for decision in (RawDecision(0, 1, "pass", True, 2, (70.0, 36.0)), RawDecision(0, 1, "shot")):
        for c in candidate_options(_snapshot(), decision, 0, constant_models(), "k"):
            assert set(c.option.factors) == set(get_args(FactorName))
            assert all(0 <= v <= 1 for v in c.option.factors.values())


def test_the_chosen_dribble_goes_where_the_player_went_and_any_other_heads_for_goal():
    snap = _snapshot()
    went = RawDecision(0, 1, "carry", target_xy=(50.0, 40.0))
    [carried] = [
        c for c in candidate_options(snap, went, 0, constant_models(), "k") if c.option.kind == "carry"
    ]
    assert carried.option.target_xy == (50.0, 40.0)
    for decision in (RawDecision(0, 1, "pass", True, 2, (70.0, 36.0)), RawDecision(0, 1, "carry", True)):
        options = candidate_options(snap, decision, 0, constant_models(), "k")
        assert next(c for c in options if c.option.kind == "carry").option.target_xy == (55.0, 36.0)


def test_a_dribble_into_a_defender_is_worth_less_than_the_same_dribble_into_space():
    snap = _snapshot()  # a defender stands at (60, 30)
    pressure_matters = Logistic(np.zeros(2), np.ones(2), np.asarray([-1.0, 0.5, 0.0]))
    models = constant_models(carry=pressure_matters)

    def dribble(to: tuple[float, float]) -> Candidate:
        options = candidate_options(snap, RawDecision(0, 1, "carry", target_xy=to), 0, models, "k")
        return next(c for c in options if c.option.kind == "carry")

    into_defender, into_space = dribble((55.0, 32.0)), dribble((55.0, 42.0))
    assert into_defender.option.p_success < into_space.option.p_success
    assert into_defender.value < into_space.value


def test_regret_is_how_much_more_the_best_alternative_was_worth():
    assert regret({"a": 0.05, "b": 0.02, "c": 0.01}, "b") == pytest.approx(0.03)
    assert regret({"a": 0.05, "b": 0.02}, "a") == 0.0
    params = fit_params(list(np.linspace(0, 1, 101)))
    assert (params.flag_threshold, params.severity_scale) == (0.85, 0.99)


def test_the_turning_point_is_the_final_decision_and_only_when_flagged():
    md = counter_attack().build()
    for a in analyse_match(md, constant_models(), STYLES, FLAG_ALL):
        p = a.possession
        assert p.flagged == (p.outcome != "goal")
        assert p.turning_point_idx == len(p.decisions) - 1
        assert [d.is_turning_point for d in p.decisions] == [False] * (len(p.decisions) - 1) + [True]
    never = EngineParams(flag_threshold=10.0, severity_scale=1.0)
    for a in analyse_match(md, constant_models(), STYLES, never):
        p = a.possession
        assert not p.flagged and p.turning_point_idx is None and not p.verdicts and not p.facts
        assert a.regret == regret(a.values[-1], p.decisions[-1].chosen_option_id)


def test_analysis_is_contract_valid_and_flagged_possessions_carry_verdicts_and_facts():
    analyses = analyse_match(counter_attack().build(), constant_models(), STYLES, FLAG_ALL)
    assert [a.possession.id for a in analyses] == [
        "2000_01_01_009-0",
        "2000_01_01_009-260",
        "2000_01_01_009-450",
    ]
    for a in analyses:
        p = Possession.model_validate_json(a.possession.model_dump_json())
        assert all(0 <= v <= 1 for d in p.decisions for o in d.options for v in o.factors.values())
        if p.flagged:
            assert set(p.verdicts) == {s.id for s in STYLES}
            assert {"tp.player", "tp.time", "chosen.p_success", "alt.player"} <= set(p.facts)


def test_a_goal_is_never_flagged():
    md = SynthMatch().hold(6, 20).pass_to(6, 9).hold(9, 20).shot(9, outcome="goal").idle(50).build()
    [goal] = analyse_match(md, constant_models(), STYLES, FLAG_ALL)
    assert goal.possession.outcome == "goal" and not goal.possession.flagged


def test_live_analysis_at_each_close_equals_offline_analysis():
    md = counter_attack().build()
    owners = dict(zip(md.possession_frames.tolist(), md.possession_pids.tolist(), strict=True))
    splitter, live = PossessionSplitter(), []
    for frame in range(md.events[-1].frame + 1):
        for poss in splitter.step(frame, owners.get(frame), [e for e in md.events if e.frame == frame]):
            live.append(analyse_possession(md.until(frame), poss, constant_models(), STYLES, FLAG_ALL))
    offline = analyse_match(md, constant_models(), STYLES, FLAG_ALL)
    closed_live = [a.possession.model_dump() for a in live if a]
    assert closed_live == [a.possession.model_dump() for a in offline][: len(closed_live)]
    assert len(closed_live) == 2
