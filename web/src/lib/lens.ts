// The tactical lens in the browser: the same arithmetic as filmroom/style.py, checked against the engine by
// contracts/parity.json. Every verdict the app shows is computed here, for presets and custom sliders alike,
// so live and offline mode agree and a slider drag never waits on the network.

import type {
  Decision,
  FlipReason,
  Option,
  SliderSpec,
  Sliders,
  StyleConfig,
  StyleLens,
  Verdict,
} from "@/contracts"
import { roundTo } from "@/lib/round"

export type FactorName = FlipReason["factor"]
export type SliderName = SliderSpec["slider"]
export const CUSTOM_STYLE_ID = "custom"

export function weightsFromSliders(
  lens: StyleLens,
  sliders: Sliders
): Record<string, number> {
  const weights: Record<string, number> = { ...lens.base }
  for (const spec of lens.sliders) {
    const position = sliders[spec.slider]
    for (const [factor, gain] of Object.entries(spec.gains)) {
      weights[factor] = (weights[factor] ?? 0) + gain * (position - 0.5)
    }
  }
  return Object.fromEntries(
    Object.entries(weights).map(([f, w]) => [f, roundTo(w, 6)])
  )
}

export function styleFromSliders(
  lens: StyleLens,
  withBall: StyleConfig["with_ball"],
  withoutBall: StyleConfig["without_ball"],
  sliders: Sliders
): StyleConfig {
  const principles = (id: string) =>
    lens.rule_sets.find((r) => r.id === id)!.principles
  return {
    id: CUSTOM_STYLE_ID,
    name: "Custom",
    with_ball: withBall,
    without_ball: withoutBall,
    sliders,
    weights: weightsFromSliders(lens, sliders),
    principles: [...principles(withBall), ...principles(withoutBall)],
  }
}

export function score(option: Option, style: StyleConfig): number {
  let total = 0
  for (const [factor, value] of Object.entries(option.factors)) {
    total += (style.weights[factor] ?? 0) * value
  }
  return total
}

/** The highest-scoring option; on a tie the first, as Python's max() picks. */
export function bestOption(decision: Decision, style: StyleConfig): Option {
  let best = decision.options[0]
  let bestScore = score(best, style)
  for (const option of decision.options.slice(1)) {
    const s = score(option, style)
    if (s > bestScore) [best, bestScore] = [option, s]
  }
  return best
}

export function flipReason(
  decision: Decision,
  reference: StyleConfig,
  style: StyleConfig
): FlipReason | null {
  const refBest = bestOption(decision, reference)
  const newBest = bestOption(decision, style)
  if (refBest.id === newBest.id) return null
  const factors = new Set([
    ...Object.keys(newBest.factors),
    ...Object.keys(refBest.factors),
  ])
  let top: { factor: string; contribution: number } | null = null
  for (const factor of factors) {
    const contribution =
      ((style.weights[factor] ?? 0) - (reference.weights[factor] ?? 0)) *
      ((newBest.factors[factor] ?? 0) - (refBest.factors[factor] ?? 0))
    if (top === null || contribution > top.contribution)
      top = { factor, contribution }
  }
  return {
    vs_style_id: reference.id,
    factor: top!.factor as FactorName,
    contribution: roundTo(top!.contribution, 4),
  }
}

export function verdict(
  decision: Decision,
  style: StyleConfig,
  reference: StyleConfig
): Verdict {
  const best = bestOption(decision, style)
  const chosen = decision.options.find(
    (o) => o.id === decision.chosen_option_id
  )!
  return {
    style_id: style.id,
    decision_idx: decision.idx,
    best_option_id: best.id,
    chosen_option_id: chosen.id,
    better_available: best.id !== chosen.id,
    margin: roundTo(score(best, style) - score(chosen, style), 4),
    flip_reason: flipReason(decision, reference, style),
  }
}

export function sliderFor(
  lens: StyleLens,
  factor: FactorName
): SliderSpec | undefined {
  return lens.sliders.find((s) => factor in s.gains)
}

/** "Counter + Low Block weights progression 2.3× higher than Possession + High Press": the flip's factor,
 * how its weight moved and the slider that moved it. */
export function flipLine(
  reason: FlipReason,
  style: StyleConfig,
  reference: StyleConfig,
  lens: StyleLens,
  factorLabel: string
): string {
  const ours = style.weights[reason.factor] ?? 0
  const theirs = reference.weights[reason.factor] ?? 0
  const ratio = theirs > 0 ? ours / theirs : Infinity
  let change: string
  if (ours >= theirs) {
    change =
      ratio >= 1.5 && Number.isFinite(ratio)
        ? `${trimmed(ratio)}× higher`
        : "higher"
  } else {
    change =
      ours > 0 && theirs / ours >= 1.5
        ? `${trimmed(theirs / ours)}× lower`
        : "lower"
  }
  const slider = sliderFor(lens, reason.factor)
  const via = slider ? ` (${slider.label.toLowerCase()})` : ""
  return `${style.name} weights ${factorLabel} ${change} than ${reference.name}${via}`
}

function trimmed(ratio: number): string {
  return ratio >= 10
    ? String(Math.round(ratio))
    : ratio.toFixed(1).replace(/\.0$/, "")
}
