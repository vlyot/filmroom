import { describe, expect, it } from "vitest"

import type { Decision, StyleConfig } from "@/contracts"
import {
  CUSTOM_STYLE_ID,
  bestOption,
  flipLine,
  styleFromSliders,
  verdict,
} from "@/lib/lens"
import { golden } from "@/lib/parity"

const reference = golden.styles[0]
const styleFor = (expected: StyleConfig): StyleConfig =>
  expected.id === CUSTOM_STYLE_ID
    ? styleFromSliders(
        golden.lens,
        expected.with_ball,
        expected.without_ball,
        expected.sliders
      )
    : golden.styles.find((s) => s.id === expected.id)!

describe("lens", () => {
  it("builds the engine's weights for every preset and custom slider set", () => {
    for (const preset of golden.styles) {
      const rebuilt = styleFromSliders(
        golden.lens,
        preset.with_ball,
        preset.without_ball,
        preset.sliders
      )
      expect(rebuilt.weights).toEqual(preset.weights)
    }
    for (const c of golden.cases.filter(
      (c) => c.style.id === CUSTOM_STYLE_ID
    )) {
      expect(styleFor(c.style)).toEqual(c.style)
    }
  })

  it("reaches the engine's verdict and flip reason in every case", () => {
    for (const c of golden.cases) {
      const possession = golden.possessions.find(
        (p) => p.id === c.possession_id
      )!
      const decision = possession.decisions[possession.turning_point_idx!]
      expect(verdict(decision, styleFor(c.style), reference)).toEqual(c.verdict)
    }
    expect(golden.cases.some((c) => c.verdict.flip_reason)).toBe(true)
  })

  it("breaks score ties in favour of the first option, as Python's max does", () => {
    const option = (id: string) => ({
      id,
      kind: "pass" as const,
      target_pid: 1,
      target_xy: null,
      p_success: 0.5,
      p_success_band: "medium" as const,
      danger_gain: 0,
      factors: { p_success: 0.5 },
    })
    const decision: Decision = {
      idx: 0,
      frame: 0,
      t_ms: 0,
      pid: 0,
      kind: "pass",
      chosen_option_id: "b",
      options: [option("a"), option("b")],
      is_turning_point: true,
    }
    expect(bestOption(decision, reference).id).toBe("a")
  })

  it("names the factor, how far its weight moved and the slider behind it", () => {
    const style = {
      ...reference,
      name: "Mine",
      weights: { ...reference.weights, progression: 1.5 },
    }
    const reason = {
      vs_style_id: reference.id,
      factor: "progression" as const,
      contribution: 0.1,
    }
    const ratio = (1.5 / reference.weights.progression)
      .toFixed(1)
      .replace(/\.0$/, "")
    expect(flipLine(reason, style, reference, golden.lens, "progression")).toBe(
      `Mine weights progression ${ratio}× higher than ${reference.name} (verticality)`
    )
    const lower = {
      ...style,
      weights: {
        ...reference.weights,
        progression: reference.weights.progression * 0.9,
      },
    }
    expect(
      flipLine(reason, lower, reference, golden.lens, "progression")
    ).toContain("progression lower than")
  })
})
