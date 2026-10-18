import { describe, expect, it } from "vitest"

import { CUSTOM_STYLE_ID, styleFromSliders } from "@/lib/lens"
import {
  SUPPORTED_LANGUAGES,
  formatFact,
  narrativeFacts,
  renderNarrative,
  templateNarrative,
} from "@/lib/narrative"
import { golden } from "@/lib/parity"

const reference = golden.styles[0]

describe("narrative", () => {
  it("supports the agent layer's languages", () => {
    expect(SUPPORTED_LANGUAGES).toEqual(["en", "es"])
  })

  it("formats every kind of slot as the engine does, per locale", () => {
    for (const { fact, language, text } of golden.formats) {
      expect(formatFact(fact, language)).toBe(text)
    }
  })

  it("builds the engine's facts and renders its text for every audience, language and style", () => {
    for (const c of golden.cases) {
      const possession = golden.possessions.find(
        (p) => p.id === c.possession_id
      )!
      const style =
        c.style.id === CUSTOM_STYLE_ID
          ? styleFromSliders(
              golden.lens,
              c.style.with_ball,
              c.style.without_ball,
              c.style.sliders
            )
          : c.style
      for (const language of SUPPORTED_LANGUAGES) {
        const facts = narrativeFacts(
          possession,
          golden.match,
          c.verdict,
          style,
          reference,
          language
        )
        expect(facts).toEqual(c.facts[language])
      }
      for (const [key, expected] of Object.entries(c.narratives)) {
        const [audience, language] = key.split(".") as [
          "coach" | "player" | "fan",
          string,
        ]
        const narrative = templateNarrative(
          possession,
          golden.match,
          c.verdict,
          style,
          reference,
          audience,
          language
        )
        expect(narrative.template).toBe(expected.template)
        expect(narrative.claims).toEqual(expected.claims)
        expect(
          renderNarrative(narrative.template, narrative.facts, language)
        ).toBe(expected.text)
      }
    }
  })
})
