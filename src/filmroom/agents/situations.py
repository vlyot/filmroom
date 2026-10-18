"""Situation vectors for "similar situations": a fixed-order vector per flagged possession, built only from
the contract (what kind of decision, where it ended, how, and the style factors of what was chosen and of
what the style rated best), compared by cosine similarity. The file and engine stores search by brute force
(`similar_in`); the database store keeps the same vectors in pgvector."""

from typing import TYPE_CHECKING, get_args

import numpy as np

from filmroom.contracts.models import ActionKind, FactorName, Possession

if TYPE_CHECKING:
    from filmroom.api.store import Store

ZONES = ("own", "mid", "final")
OUTCOME_GROUPS = {"lost_pass": 0, "lost_tackle": 0, "shot": 1, "goal": 1, "out": 2, "stoppage": 2}
SITUATION_DIM = len(get_args(ActionKind)) + len(ZONES) + 3 + 2 * len(get_args(FactorName))


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


def similar_in(
    store: "Store", possession_id: str, style_id: str, k: int, all_matches: bool
) -> list[tuple[Possession, float]]:
    """`Store.similar` by brute force over the store's possessions: the target's match, or every match."""
    target = store.possession(possession_id)
    match_ids = [m.id for m in store.matches()] if all_matches else [target.match_id]
    pool = [p for m in match_ids for p in store.match_possessions(m)]
    return most_similar(target, pool, style_id, k)
