"""The tactical lens: styles built from four sliders, and linear option scoring under them.

Weights are base + gain * (slider - 0.5), summed over sliders, and an option's score is the sum of weight *
factor. Both steps are linear, so the browser re-scores custom sliders the same way and every verdict flip
traces to one factor and the one slider behind it. Presets are pairs of rule sets (with / without the ball),
each fixing two sliders.
"""

from functools import cache
from pathlib import Path

from filmroom.contracts.models import (
    Contract,
    Decision,
    FactorName,
    FlipReason,
    Option,
    RuleSet,
    Sliders,
    SliderSpec,
    StyleConfig,
    StyleLens,
    Verdict,
    WithBall,
    WithoutBall,
)

LENS_PATH = Path(__file__).with_name("styles.json")
CUSTOM_STYLE_ID = "custom"


class PresetSpec(Contract):
    id: str
    name: str
    with_ball: WithBall
    without_ball: WithoutBall


class LensConfig(Contract):
    base: dict[FactorName, float]
    sliders: list[SliderSpec]
    rule_sets: list[RuleSet]
    presets: list[PresetSpec]  # the first is the reference that flip reasons are measured against

    def rule_set(self, rule_set_id: str) -> RuleSet:
        return next(r for r in self.rule_sets if r.id == rule_set_id)


@cache
def load_lens(path: Path = LENS_PATH) -> LensConfig:
    return LensConfig.model_validate_json(path.read_bytes())


def weights_from_sliders(lens: LensConfig, sliders: Sliders) -> dict[FactorName, float]:
    weights = dict(lens.base)
    for spec in lens.sliders:
        position = getattr(sliders, spec.slider)
        for factor, gain in spec.gains.items():
            weights[factor] = weights.get(factor, 0.0) + gain * (position - 0.5)
    return {factor: round(w, 6) for factor, w in weights.items()}


def style_from_sliders(
    lens: LensConfig,
    with_ball: WithBall,
    without_ball: WithoutBall,
    sliders: Sliders,
    style_id: str = CUSTOM_STYLE_ID,
    name: str = "Custom",
) -> StyleConfig:
    return StyleConfig(
        id=style_id,
        name=name,
        with_ball=with_ball,
        without_ball=without_ball,
        sliders=sliders,
        weights=weights_from_sliders(lens, sliders),
        principles=lens.rule_set(with_ball).principles + lens.rule_set(without_ball).principles,
    )


def presets(lens: LensConfig) -> list[StyleConfig]:
    """The named presets, reference first; each takes its sliders from its two rule sets."""
    return [
        style_from_sliders(
            lens,
            p.with_ball,
            p.without_ball,
            Sliders(**lens.rule_set(p.with_ball).sliders, **lens.rule_set(p.without_ball).sliders),
            p.id,
            p.name,
        )
        for p in lens.presets
    ]


def public_lens(lens: LensConfig) -> StyleLens:
    return StyleLens(
        reference_style_id=lens.presets[0].id, base=lens.base, sliders=lens.sliders, rule_sets=lens.rule_sets
    )


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
