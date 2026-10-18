import type { PossessionSummary } from "@/contracts"

/** Match clock, as the engine writes it (filmroom.engine.assemble.mmss). */
export function mmss(ms: number): string {
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${pad(Math.floor(ms / 60000))}:${pad(Math.floor(ms / 1000) % 60)}`
}

export const OUTCOME_LABELS: Record<PossessionSummary["outcome"], string> = {
  shot: "Shot",
  goal: "Goal",
  lost_tackle: "Lost in a tackle",
  lost_pass: "Pass cut out",
  out: "Ball out",
  stoppage: "Stoppage",
}

export const ZONE_LABELS: Record<PossessionSummary["ended_zone"], string> = {
  own: "own third",
  mid: "midfield",
  final: "final third",
}

export const MODE_LABELS: Record<string, string> = {
  human_vs_human: "Human v human",
  human_vs_ai: "Human v AI",
  ai_vs_ai: "AI v AI",
}
