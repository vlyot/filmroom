import { useMemo } from "react"

import type { Decision, Possession, Verdict } from "@/contracts"
import { verdict } from "@/lib/lens"
import { useActiveStyle } from "@/state/preferences"

export type Judged = {
  decision: Decision
  /** The verdict under the active style, with the flip reason against the reference preset. */
  verdict: Verdict
  /** The reference preset's own verdict, to say whether the active style changed it. */
  referenceVerdict: Verdict
}

/** A flagged possession's decision judged under the active style, in the browser. Defaults to the turning
 * point; null for a possession that wasn't flagged. */
export function useJudged(
  possession: Possession | null,
  decisionIdx?: number
): Judged | null {
  const { style, reference } = useActiveStyle()
  return useMemo(() => {
    if (!possession || possession.turning_point_idx === null) return null
    const decision =
      possession.decisions[decisionIdx ?? possession.turning_point_idx]
    return {
      decision,
      verdict: verdict(decision, style, reference),
      referenceVerdict: verdict(decision, reference, reference),
    }
  }, [possession, decisionIdx, style, reference])
}
