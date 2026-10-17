"""Situation vectors for "similar situations": a fixed-order vector per flagged possession, built only from
the contract (what kind of decision, where it ended, how, and the style factors of what was chosen and of
what the reference style rated best), compared by cosine similarity. Brute force is fine at a few hundred
flagged moments per match; Phase 5 stores the same vectors in pgvector."""

from typing import get_args

import numpy as np

from filmroom.contracts.models import ActionKind, FactorName, Possession

ZONES = ("own", "mid", "final")
OUTCOME_GROUPS = {"lost_pass": 0, "lost_tackle": 0, "shot": 1, "goal": 1, "out": 2, "stoppage": 2}


def _one_hot(index: int, size: int) -> list[float]:
    return [1.0 if i == index else 0.0 for i in range(size)]


def situation_vector(possession: Possession, reference_id: str) -> np.ndarray:
    verdict = possession.verdicts[reference_id]
    decision = possession.decisions[verdict.decision_idx]
    options = {o.id: o for o in decision.options}
    chosen, best = options[verdict.chosen_option_id], options[verdict.best_option_id]
    kinds = get_args(ActionKind)
    return np.asarray(
        _one_hot(kinds.index(decision.kind), len(kinds))
        + _one_hot(ZONES.index(possession.ended_zone), len(ZONES))
        + _one_hot(OUTCOME_GROUPS[possession.outcome], 3)
        + [chosen.factors.get(f, 0.0) for f in get_args(FactorName)]
        + [best.factors.get(f, 0.0) for f in get_args(FactorName)]
    )


def most_similar(
    target: Possession, candidates: list[Possession], reference_id: str, k: int
) -> list[tuple[Possession, float]]:
    """The k flagged candidates closest to the target, most similar first; the target itself is left out."""
    pool = [c for c in candidates if c.flagged and c.id != target.id]
    if not pool:
        return []
    query = situation_vector(target, reference_id)
    matrix = np.stack([situation_vector(c, reference_id) for c in pool])
    scores = matrix @ query / (np.linalg.norm(matrix, axis=1) * np.linalg.norm(query))
    order = np.argsort(-scores, kind="stable")[:k]
    return [(pool[i], round(float(scores[i]), 4)) for i in order]
