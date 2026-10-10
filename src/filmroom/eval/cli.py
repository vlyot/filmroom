"""Score turning-point predictions against a labelled set.

Usage: uv run filmroom-eval [--set tuning|holdout]
Until the Phase 1 detector exists, predictions come from the fixtures (a stub source), so only labels with a
fixture are scored.
"""

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Protocol

from filmroom.api.store import FixtureStore
from filmroom.config import Settings
from filmroom.data.catalog import Catalog
from filmroom.eval.labels import LabelRecord, load_labels
from filmroom.eval.scoring import (
    DecisionPoint,
    Score,
    final_action_predictions,
    label_decision_idx,
    random_expected,
    score,
)


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


def report(scores: list[Score]) -> str:
    lines = [f"{'method':<20} {'n':>3}  {'exact':>16}  {'near (±1)':>16}"]
    for s in scores:
        lo, hi = s.exact_ci
        nlo, nhi = s.near_ci
        rate = (s.exact / s.n) if s.n else 0.0
        near = (s.near / s.n) if s.n else 0.0
        lines.append(
            f"{s.method:<20} {s.n:>3}  {rate:>5.0%} [{lo:.0%}–{hi:.0%}]  {near:>5.0%} [{nlo:.0%}–{nhi:.0%}]"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", choices=["tuning", "holdout"], default="tuning")
    args = parser.parse_args()
    settings = Settings()
    catalog = Catalog(settings)
    path = settings.labels_path if args.set == "tuning" else settings.holdout_path
    labels = load_labels(path, args.set, lambda m: catalog.load(m).clock)
    scores = evaluate(labels, FixtureDecisionSource(FixtureStore(settings.fixtures_dir)))
    print(f"{args.set} set: {len(labels)} labels\n{report(scores)}")
    out = settings.cache_dir / "eval"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (out / f"{args.set}-{stamp}.json").write_text(json.dumps([asdict(s) for s in scores], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
