"""Engine checks against the labelled set: map each label to an engine possession, and score whether the
engine's best alternatives at the labelled decision include the player the label says was the better option.
The bar (top three on at least half the rows) was fixed on 11 Oct before measuring (PRD v3.3, §4.3)."""

from dataclasses import dataclass

from filmroom.data.catalog import match_slug
from filmroom.data.positions import team_of
from filmroom.engine.analyse import PossessionAnalysis
from filmroom.eval.labels import LabelRecord
from filmroom.eval.scoring import DecisionPoint, label_decision_idx, wilson_ci

TOP_K = 3


@dataclass(frozen=True)
class Case:
    label: LabelRecord
    analysis: PossessionAnalysis
    truth: int | None  # index of the labelled decision; None if no decision is within tolerance


def match_label(label: LabelRecord, analyses: list[PossessionAnalysis]) -> PossessionAnalysis | None:
    """The engine possession of the labelled team that overlaps the labelled window most."""
    slug, team = match_slug(label.match_id), team_of(label.tp_pid)

    def overlap(a: PossessionAnalysis) -> int:
        p = a.possession
        return min(p.end_frame, label.end_frame) - max(p.start_frame, label.start_frame)

    mine = [a for a in analyses if a.possession.match_id == slug and a.possession.team == team]
    best = max(mine, key=overlap, default=None)
    return best if best is not None and overlap(best) > 0 else None


def build_cases(labels: list[LabelRecord], analyses: dict[str, list[PossessionAnalysis]]) -> list[Case]:
    cases = []
    for label in labels:
        analysis = match_label(label, analyses[label.match_id])
        if analysis is not None:
            points = [DecisionPoint(d.frame, d.pid) for d in analysis.possession.decisions]
            cases.append(Case(label, analysis, label_decision_idx(label, points)))
    return cases


def ranked_alternatives(case: Case) -> list[int]:
    """Teammates the passer could have found instead, most valuable first."""
    decision = case.analysis.possession.decisions[case.truth]
    values = case.analysis.values[case.truth]
    passes = [
        o
        for o in decision.options
        if o.kind == "pass" and o.target_pid is not None and o.id != decision.chosen_option_id
    ]
    return [o.target_pid for o in sorted(passes, key=lambda o: values[o.id], reverse=True)]


@dataclass(frozen=True)
class AgreementResult:
    n: int
    top1: int
    top_k: int
    random_top1: float  # expected hits if alternatives were picked at random
    random_top_k: float

    @property
    def passed(self) -> bool:
        return self.top_k * 2 >= self.n

    def ci(self, hits: int) -> tuple[float, float]:
        return wilson_ci(hits, self.n)


def alternatives_agreement(cases: list[Case]) -> AgreementResult:
    eligible = [c for c in cases if c.truth is not None and c.label.better_pid is not None]
    top1 = top_k = 0
    random_top1 = random_top_k = 0.0
    for case in eligible:
        ranked = ranked_alternatives(case)
        top1 += ranked[:1] == [case.label.better_pid]
        top_k += case.label.better_pid in ranked[:TOP_K]
        if case.label.better_pid in ranked:
            random_top1 += 1 / len(ranked)
            random_top_k += min(TOP_K, len(ranked)) / len(ranked)
    return AgreementResult(len(eligible), top1, top_k, random_top1, random_top_k)
