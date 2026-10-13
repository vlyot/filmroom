"""Check the engine against the labelled set and report pass-model calibration.

Usage:
  uv run filmroom-eval                    what was on instead (the v3.3 bar) and turning points vs the labels
  uv run filmroom-eval --thresholds       first refit the flag threshold and severity scale over all matches
                                          (no labels); writes engine/params.json
  uv run filmroom-eval --calibration      pass- and shot-model calibration out of fold, with a reliability
                                          plot for passes
  uv run filmroom-eval --lens             tactical lens over every match: preset disagreement, flip
                                          attribution, slider directions and flag rates by final action
  uv run filmroom-eval --source fixtures  score the Phase 0 fixtures instead of the engine
"""

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Protocol

from filmroom.api.store import FixtureStore
from filmroom.config import Settings
from filmroom.data.catalog import Catalog
from filmroom.engine.analyse import PossessionAnalysis, analyse_match
from filmroom.engine.training import fit_lomo, load_rows
from filmroom.engine.turning_point import EngineParams, fit_params, load_params, save_params
from filmroom.eval.agreement import TOP_K, AgreementResult, Case, alternatives_agreement, build_cases
from filmroom.eval.calibration import (
    CalibrationReport,
    calibration_report,
    out_of_fold,
    plot,
    shot_out_of_fold,
)
from filmroom.eval.labels import LabelRecord, load_labels
from filmroom.eval.lens import (
    BAND,
    attribution,
    direction_violations,
    disagreement,
    flag_rates,
    flagged_turning_points,
)
from filmroom.eval.scoring import (
    DecisionPoint,
    Score,
    final_action_predictions,
    label_decision_idx,
    random_expected,
    score,
)
from filmroom.style import load_lens, presets


class DecisionSource(Protocol):
    name: str

    def decisions(self, label: LabelRecord) -> list[DecisionPoint] | None: ...
    def prediction(self, label: LabelRecord) -> int | None: ...


class FixtureDecisionSource:
    name = "fixtures (stub)"

    def __init__(self, store: FixtureStore):
        self.by_label = {f.label_id: f.possession for f in store.all_fixtures() if f.label_id}

    def decisions(self, label: LabelRecord) -> list[DecisionPoint] | None:
        p = self.by_label.get(label.id)
        return [DecisionPoint(d.frame, d.pid) for d in p.decisions] if p else None

    def prediction(self, label: LabelRecord) -> int | None:
        return self.by_label[label.id].turning_point_idx


def evaluate(labels: list[LabelRecord], source: DecisionSource) -> list[Score]:
    truth, predictions, n_decisions = {}, {}, {}
    for label in labels:
        decisions = source.decisions(label)
        if decisions is None:
            continue
        truth[label.id] = label_decision_idx(label, decisions)
        predictions[label.id] = source.prediction(label)
        n_decisions[label.id] = len(decisions)
    return [
        score(source.name, predictions, truth),
        score("final action", final_action_predictions(n_decisions), truth),
        random_expected(truth, n_decisions),
    ]


def turning_point_context(cases: list[Case]) -> list[Score]:
    """How often the labelled turning point is the final decision, which is where the engine places it."""
    truth = {c.label.id: c.truth for c in cases}
    n_decisions = {c.label.id: len(c.analysis.possession.decisions) for c in cases}
    return [
        score("final decision", final_action_predictions(n_decisions), truth),
        random_expected(truth, n_decisions),
    ]


def report(scores: list[Score]) -> str:
    lines = [f"{'method':<22} {'n':>3}  {'exact':>16}  {'near (±1)':>16}"]
    for s in scores:
        lo, hi = s.exact_ci
        nlo, nhi = s.near_ci
        rate = (s.exact / s.n) if s.n else 0.0
        near = (s.near / s.n) if s.n else 0.0
        lines.append(
            f"{s.method:<22} {s.n:>3}  {rate:>5.0%} [{lo:.0%}–{hi:.0%}]  {near:>5.0%} [{nlo:.0%}–{nhi:.0%}]"
        )
    return "\n".join(lines)


def agreement_report(r: AgreementResult) -> str:
    def row(name: str, hits: int, random: float) -> str:
        lo, hi = r.ci(hits)
        rate = f"{hits / r.n:>4.0%} [{lo:.0%}–{hi:.0%}]"
        return f"  {name:<6} {hits:>2} of {r.n} = {rate}   random {random / r.n:.0%}"

    verdict = "PASS" if r.passed else "FAIL"
    return "\n".join(
        [
            "What was on instead: is the labelled better player among the engine's best alternatives?",
            row("top 1", r.top1, r.random_top1),
            row(f"top {TOP_K}", r.top_k, r.random_top_k),
            f"  bar (fixed 11 Oct): top {TOP_K} on at least half the rows: {verdict}",
        ]
    )


def calibration_text(r: CalibrationReport) -> str:
    lines = [
        f"{r.n} real pass attempts, {r.observed_rate:.0%} completed",
        f"Brier {r.brier:.4f} (always the completion rate: {r.base_rate_brier:.4f}), ECE {r.ece:.4f}",
        f"{'predicted':>12} {'n':>6} {'mean p':>8} {'observed':>9}",
    ]
    lines += [
        f"{b.lo:>5.1f}–{b.hi:<5.1f} {b.n:>6} {b.mean_p:>8.3f} {b.observed:>9.3f}" for b in r.bins if b.n
    ]
    lines += [f"band {name:<7} {b.n:>6} {b.mean_p:>8.3f} {b.observed:>9.3f}" for name, b in r.bands.items()]
    return "\n".join(lines)


def shot_calibration_text(reports: dict[str, CalibrationReport]) -> str:
    return "\n".join(
        f"shots, {name:<9} {r.n} real shots, observed {r.observed_rate:.0%}: Brier {r.brier:.4f} "
        f"(always the observed rate: {r.base_rate_brier:.4f}), ECE {r.ece:.4f}"
        for name, r in reports.items()
    )


def lens_report(analyses: list[PossessionAnalysis], params: EngineParams) -> tuple[str, dict]:
    lens = load_lens()
    styles = presets(lens)
    decisions = flagged_turning_points(analyses, params)
    pairs = disagreement(decisions, styles)
    attributed = attribution(decisions, styles)
    directions = direction_violations(decisions, lens, styles)
    rates = flag_rates(analyses, params)
    lines = [f"Tactical lens over {len(decisions)} flagged moments (sanity band {BAND[0]:.0%}-{BAND[1]:.0%})"]
    lines += [
        f"  {p.a:<22} vs {p.b:<22} {p.rate:>4.0%}{'' if p.in_band else '  outside band'}" for p in pairs
    ]
    lines.append(
        f"Flip attribution: {attributed.flips - len(attributed.failures)} of {attributed.flips} flips "
        f"({attributed.rate:.0%}) trace to a factor both cards name; by factor {attributed.by_factor}"
    )
    lines += [f"  FAIL {f}" for f in attributed.failures[:10]]
    lines.append(f"Slider direction violations: {directions}")
    lines.append(
        "Flag rate by final action: "
        + ", ".join(f"{k} {f}/{n} = {f / n:.0%}" for k, (f, n) in rates.items() if n)
    )
    result = {
        "disagreement": [asdict(p) | {"rate": p.rate} for p in pairs],
        "attribution": asdict(attributed) | {"rate": attributed.rate},
        "direction_violations": directions,
        "flag_rates": rates,
    }
    return "\n".join(lines), result


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--set", choices=["tuning", "holdout"], default="tuning")
    parser.add_argument("--source", choices=["engine", "fixtures"], default="engine")
    parser.add_argument("--thresholds", action="store_true")
    parser.add_argument("--calibration", action="store_true")
    parser.add_argument("--lens", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    catalog = Catalog(settings)
    out = settings.cache_dir / "eval"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    if args.calibration:
        rows = load_rows(catalog, settings.cache_dir)
        models = fit_lomo(rows)
        result = calibration_report(*out_of_fold(rows, models))
        shots = calibration_report(*shot_out_of_fold(rows, models))
        print(calibration_text(result))
        print(shot_calibration_text(shots))
        plot(result, out / f"calibration-{stamp}.png")
        body = asdict(result) | {"xg": asdict(shots)}
        (out / f"calibration-{stamp}.json").write_text(json.dumps(body, indent=1))
        print(f"plot and JSON written to {out}")
        return 0

    path = settings.labels_path if args.set == "tuning" else settings.holdout_path
    labels = load_labels(path, args.set, lambda m: catalog.load(m).clock)
    if args.source == "fixtures":
        scores = evaluate(labels, FixtureDecisionSource(FixtureStore(settings.fixtures_dir)))
        print(f"{args.set} set: {len(labels)} labels\n{report(scores)}")
        (out / f"{args.set}-{stamp}.json").write_text(json.dumps([asdict(s) for s in scores], indent=1))
        return 0

    rows = load_rows(catalog, settings.cache_dir)
    models = fit_lomo(rows)
    styles = presets(load_lens())
    params = load_params()
    wanted = rows if args.thresholds or args.lens else {label.match_id for label in labels}
    analyses = {m: analyse_match(catalog.load(m), models[m], styles, params) for m in wanted}
    if args.thresholds:
        params = fit_params(
            [a.regret for match in analyses.values() for a in match if a.possession.outcome != "goal"]
        )
        save_params(params)
        print(f"wrote engine/params.json: {params.model_dump()}")
    cases = build_cases(labels, analyses)
    agreement = alternatives_agreement(cases)
    context = turning_point_context(cases)
    print(f"{args.set} set: {len(labels)} labels\n\n{agreement_report(agreement)}\n")
    print(
        f"Turning point = final decision; how the labels compare (context, not a score):\n{report(context)}"
    )
    result = {
        "params": params.model_dump(),
        "alternatives": asdict(agreement) | {"passed": agreement.passed},
        "turning_point_context": [asdict(s) for s in context],
    }
    if args.lens:
        text, result["lens"] = lens_report([a for match in analyses.values() for a in match], params)
        print(f"\n{text}")
    (out / f"{args.set}-{stamp}.json").write_text(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
