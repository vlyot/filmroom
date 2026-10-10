"""Linear style scoring: option score = sum(weight * factor). The web app re-scores offline the same way."""

from filmroom.contracts.models import Decision, FlipReason, Option, StyleConfig, Verdict


def score(option: Option, style: StyleConfig) -> float:
    return sum(style.weights.get(factor, 0.0) * value for factor, value in option.factors.items())


def best_option(decision: Decision, style: StyleConfig) -> Option:
    return max(decision.options, key=lambda o: score(o, style))


def flip_reason(decision: Decision, reference: StyleConfig, style: StyleConfig) -> FlipReason | None:
    """Why `style` picks a different best option than `reference`: the factor contributing most to the flip,
    contribution_k = (w_style,k - w_ref,k) * (f_k(best under style) - f_k(best under reference))."""
    ref_best, new_best = best_option(decision, reference), best_option(decision, style)
    if ref_best.id == new_best.id:
        return None
    contributions = {
        factor: (style.weights.get(factor, 0.0) - reference.weights.get(factor, 0.0))
        * (new_best.factors.get(factor, 0.0) - ref_best.factors.get(factor, 0.0))
        for factor in set(new_best.factors) | set(ref_best.factors)
    }
    factor = max(contributions, key=lambda f: contributions[f])
    return FlipReason(vs_style_id=reference.id, factor=factor, contribution=round(contributions[factor], 4))


def verdict(decision: Decision, style: StyleConfig, reference: StyleConfig) -> Verdict:
    best = best_option(decision, style)
    chosen = next(o for o in decision.options if o.id == decision.chosen_option_id)
    return Verdict(
        style_id=style.id,
        decision_idx=decision.idx,
        best_option_id=best.id,
        chosen_option_id=chosen.id,
        better_available=best.id != chosen.id,
        margin=round(score(best, style) - score(chosen, style), 4),
        flip_reason=flip_reason(decision, reference, style),
    )
