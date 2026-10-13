from types import SimpleNamespace

import pytest

from filmroom.contracts.models import Decision, Option
from filmroom.eval.agreement import Case, alternatives_agreement, match_label, ranked_alternatives
from filmroom.eval.labels import LabelRecord


def _label(lid: str = "L", better: int | None = 3) -> LabelRecord:
    return LabelRecord(lid, "tuning", "Match_2000_01_01_#001", 100, 900, 5, 500, 9, better, True, 3)


def _option(oid: str, kind: str = "pass", target: int | None = None) -> Option:
    factors = dict.fromkeys(
        ("p_success", "danger_gain", "progression", "receiver_space", "lane_openness"), 0.5
    )
    return Option(
        id=oid,
        kind=kind,
        target_pid=target,
        target_xy=None,
        p_success=0.5,
        p_success_band="medium",
        danger_gain=0.0,
        factors=factors | {"switch_of_play": 0.0},
    )


def _case(values: dict[str, float], chosen: str, better: int | None = 3, truth: int | None = 0) -> Case:
    options = [
        _option(oid, "carry" if oid == "carry" else "pass", None if oid == "carry" else int(oid))
        for oid in values
    ]
    decision = Decision(
        idx=0,
        frame=500,
        t_ms=5000,
        pid=9,
        kind="pass",
        chosen_option_id=chosen,
        options=options,
        is_turning_point=False,
    )
    analysis = SimpleNamespace(possession=SimpleNamespace(decisions=[decision]), values=[values])
    return Case(_label(better=better), analysis, truth)


def test_alternatives_are_teammates_ranked_by_value_without_the_choice_or_dribbles():
    case = _case({"1": 0.01, "2": 0.05, "3": 0.03, "4": 0.04, "carry": 0.09}, chosen="4")
    assert ranked_alternatives(case) == [2, 3, 1]


def test_agreement_counts_top_1_and_top_3_against_random_picks():
    cases = [
        _case({"1": 0.01, "2": 0.05, "3": 0.06, "4": 0.04}, chosen="1"),  # labelled 3 ranked first
        _case({"1": 0.01, "2": 0.05, "3": 0.03, "4": 0.04, "5": 0.02, "6": 0.0}, chosen="1"),  # third
        _case({"1": 0.01, "2": 0.05, "3": 0.00, "4": 0.04, "5": 0.02, "6": 0.03}, chosen="1"),  # fifth
        _case({"1": 0.01, "2": 0.05}, chosen="1", better=None),  # no better option labelled: not scored
        _case({"1": 0.01, "2": 0.05}, chosen="1", truth=None),  # no decision near the label: not scored
    ]
    result = alternatives_agreement(cases)
    assert (result.n, result.top1, result.top_k) == (3, 1, 2)
    assert result.random_top1 == pytest.approx(1 / 3 + 1 / 5 + 1 / 5)
    assert result.random_top_k == pytest.approx(1 + 3 / 5 + 3 / 5)
    assert result.passed


def test_a_label_maps_to_the_same_team_possession_it_overlaps_most():
    def analysis(team: int, start: int, end: int):
        p = SimpleNamespace(match_id="2000_01_01_001", team=team, start_frame=start, end_frame=end)
        return SimpleNamespace(possession=p)

    other_team, small, big = analysis(1, 100, 900), analysis(0, 0, 200), analysis(0, 300, 1000)
    assert match_label(_label(), [other_team, small, big]) is big
    assert match_label(_label(), [analysis(0, 2000, 3000)]) is None
