"""Checks on the tactical lens over engine output (PRD §4.5): how often presets disagree on flagged moments
(sanity band 15-60%), whether every flip traces to a factor both style cards name, whether slider sweeps move
rankings only in each slider's stated direction, and how flag rates split by the possession's final action.
Flags are recomputed from each possession's regret under the given params, so a threshold refit and this
report can run in one pass."""

import itertools
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from filmroom.contracts.models import Decision, StyleConfig
from filmroom.engine.analyse import PossessionAnalysis
from filmroom.engine.turning_point import EngineParams
from filmroom.style import LensConfig, best_option, flip_reason, score, style_from_sliders

BAND = (0.15, 0.60)
SWEEP_POSITIONS = np.linspace(0, 1, 11)


def is_flagged(analysis: PossessionAnalysis, params: EngineParams) -> bool:
    return analysis.possession.outcome != "goal" and analysis.regret >= params.flag_threshold


def flagged_turning_points(analyses: list[PossessionAnalysis], params: EngineParams) -> list[Decision]:
    return [a.possession.decisions[-1] for a in analyses if is_flagged(a, params)]


@dataclass(frozen=True)
class PairDisagreement:
    a: str
    b: str
    n: int
    disagree: int

    @property
    def rate(self) -> float:
        return self.disagree / self.n if self.n else 0.0

    @property
    def in_band(self) -> bool:
        return BAND[0] <= self.rate <= BAND[1]


def disagreement(decisions: list[Decision], styles: list[StyleConfig]) -> list[PairDisagreement]:
    best = {s.id: [best_option(d, s).id for d in decisions] for s in styles}
    return [
        PairDisagreement(
            a.id, b.id, len(decisions), sum(x != y for x, y in zip(best[a.id], best[b.id], strict=True))
        )
        for a, b in itertools.combinations(styles, 2)
    ]


@dataclass(frozen=True)
class Attribution:
    flips: int
    by_factor: dict[str, int]
    failures: list[str] = field(default_factory=list)  # "style vs style at decision: factor"

    @property
    def rate(self) -> float:
        return (self.flips - len(self.failures)) / self.flips if self.flips else 1.0


def attribution(decisions: list[Decision], styles: list[StyleConfig]) -> Attribution:
    """Every flip between two presets must be attributed to a factor with a positive share, weighted
    differently by the two, and named by a principle on both cards."""
    flips, factors, failures = 0, Counter(), []
    for a, b in itertools.combinations(styles, 2):
        named = {p.factor for p in a.principles} & {p.factor for p in b.principles}
        for d in decisions:
            reason = flip_reason(d, a, b)
            if reason is None:
                continue
            flips += 1
            factors[reason.factor] += 1
            differs = a.weights.get(reason.factor, 0.0) != b.weights.get(reason.factor, 0.0)
            if reason.contribution <= 0 or not differs or reason.factor not in named:
                failures.append(f"{a.id} vs {b.id} at {d.frame}: {reason.factor}")
    return Attribution(flips, dict(factors.most_common()), failures)


def direction_violations(
    decisions: list[Decision], lens: LensConfig, starts: list[StyleConfig]
) -> dict[str, int]:
    """For each slider, sweep it from 0 to 1 from every preset's position on every decision. A violation is a
    pair where o1 is at least as good as o2 on every factor the slider moves, in the direction of its gain,
    yet o1 falls from level-or-ahead to behind as the slider rises."""
    out = {}
    for spec in lens.sliders:
        violations = 0
        for start in starts:
            styles = [
                style_from_sliders(
                    lens,
                    start.with_ball,
                    start.without_ball,
                    start.sliders.model_copy(update={spec.slider: x}),
                )
                for x in SWEEP_POSITIONS
            ]
            for d in decisions:
                factors = np.asarray([[o.factors.get(f, 0.0) for f in spec.gains] for o in d.options])
                signs = np.sign(np.asarray(list(spec.gains.values())))
                # qualifies[i, j]: option i is at least as good as option j on every factor this slider moves
                qualifies = ((factors[:, None, :] - factors[None, :, :]) * signs >= 0).all(axis=-1)
                scores = np.asarray([[score(o, s) for o in d.options] for s in styles])
                ahead = scores[:, :, None] >= scores[:, None, :] - 1e-9
                fell = (ahead[:-1] & ~ahead[1:]).any(axis=0)
                violations += int((qualifies & fell).sum())
        out[spec.slider] = violations
    return out


def flag_rates(analyses: list[PossessionAnalysis], params: EngineParams) -> dict[str, tuple[int, int]]:
    """Flagged and total possessions by the kind of the final decision (pass, shot or dribble)."""
    totals, flagged = Counter(), Counter()
    for a in analyses:
        kind = a.possession.decisions[-1].kind
        totals[kind] += 1
        flagged[kind] += is_flagged(a, params)
    totals["all"], flagged["all"] = sum(totals.values()), sum(flagged.values())
    return {k: (flagged[k], totals[k]) for k in ("pass", "shot", "carry", "all")}
