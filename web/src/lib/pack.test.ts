import { describe, expect, it } from "vitest"

import type { SessionPack } from "@/contracts"
import { verdict } from "@/lib/lens"
import { templateNarrative } from "@/lib/narrative"
import { momentTime, packMarkdown } from "@/lib/pack"
import { golden } from "@/lib/parity"

const reference = golden.styles[0]
const possession = golden.possessions[0]
const decision = possession.decisions[possession.turning_point_idx!]
const judged = verdict(decision, reference, reference)
const narrative = templateNarrative(
  possession,
  golden.match,
  judged,
  reference,
  reference,
  "coach",
  "en"
)
const summary = { ...possession, decisions: undefined }

const pack: SessionPack = {
  match_id: golden.match.id,
  team: 0,
  style_id: reference.id,
  period: "half",
  audience: "coach",
  language: "en",
  themes: [
    {
      title: "Forcing it",
      summary: "Passes into traffic.",
      possession_ids: [possession.id],
      status: "verified",
    },
  ],
  moments: [{ rank: 1, summary, verdict: judged, narrative }],
  style_shifts: [
    {
      style_id: golden.styles[5].id,
      name: golden.styles[5].name,
      changed: 1,
      factor: "progression",
    },
  ],
}

describe("session pack export", () => {
  it("times each moment at its decision, as the narrative does", () => {
    expect(momentTime(pack.moments[0])).toBe(narrative.facts["tp.time"].value)
  })

  it("writes themes, narrated moments and the other styles as Markdown", () => {
    const markdown = packMarkdown(pack, golden.match, golden.styles)
    expect(markdown).toContain(
      `# ${golden.match.teams[0].name}: half-time session`
    )
    expect(markdown).toContain(
      "### Forcing it\n\nPasses into traffic.\n\nMoments: #1"
    )
    expect(markdown).toContain(`### #1 · ${momentTime(pack.moments[0])}`)
    expect(markdown).not.toMatch(/\{[a-z.]+\}/)
    expect(markdown).toContain(
      `| ${golden.styles[5].name} | 1 of 1 | progression |`
    )
  })
})
