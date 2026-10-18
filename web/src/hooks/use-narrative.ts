import { useEffect, useEffectEvent, useMemo, useState } from "react"

import type { Match, Narrative, Possession } from "@/contracts"
import { verdict } from "@/lib/lens"
import { renderNarrative, templateNarrative } from "@/lib/narrative"
import { narrativeKey } from "@/lib/replay/store"
import { useActiveStyle, usePreferences } from "@/state/preferences"
import { useReplaySnapshot } from "@/state/replay"
import { useSource } from "@/state/source"

const POLL_MS = 3000
const POLL_FOR_MS = 60000
const SLOW_MS = 10000

export type NarrativeView = {
  text: string
  status: Narrative["status"]
  model: string | null
  /** Still pending after about ten seconds: say the full narrative is on its way. */
  slow: boolean
}

type Fetched = {
  key: string | null
  narrative: Narrative | null
  failed: boolean
  slow: boolean
}

/** The narrative for a flagged possession under the active style, audience and language. Presets: the
 * source's narrative, polled while pending and replaced by the replay's push when it comes first. Custom
 * sliders, or a narrative the source doesn't have: a template built in the browser. */
export function useNarrative(
  possession: Possession,
  match: Match
): NarrativeView {
  const source = useSource()
  const { style, reference, presetId, isCustom } = useActiveStyle()
  const { audience, language } = usePreferences()
  const { pushed } = useReplaySnapshot()
  const key = isCustom
    ? null
    : narrativeKey({
        possession_id: possession.id,
        style_id: presetId,
        audience,
        language,
      })
  const fetched = useFetched(key, () =>
    source.narrative(possession.id, { style: presetId, audience, language })
  )

  const local = useMemo(() => {
    const decision = possession.decisions[possession.turning_point_idx!]
    const judged = verdict(decision, style, reference)
    return templateNarrative(
      possession,
      match,
      judged,
      style,
      reference,
      audience,
      language
    )
  }, [possession, match, style, reference, audience, language])

  const remote = (key && pushed[key]) || fetched.narrative
  const narrative = !isCustom && remote ? remote : local
  const waiting = !isCustom && !remote && !fetched.failed
  return {
    text: renderNarrative(narrative.template, narrative.facts, language),
    status: waiting ? "pending" : narrative.status,
    model: narrative.model ?? null,
    slow: (waiting || narrative.status === "pending") && fetched.slow,
  }
}

function useFetched(
  key: string | null,
  load: () => Promise<Narrative>
): Fetched {
  const [state, setState] = useState<Fetched>({
    key: null,
    narrative: null,
    failed: false,
    slow: false,
  })
  const run = useEffectEvent(load)

  useEffect(() => {
    if (key === null) return
    let current = true
    let poll: ReturnType<typeof setTimeout> | undefined
    const started = Date.now()
    const fetchOnce = async () => {
      try {
        const narrative = await run()
        if (!current) return
        setState((s) => ({
          key,
          narrative,
          failed: false,
          slow: s.key === key && s.slow,
        }))
        if (
          narrative.status === "pending" &&
          Date.now() - started < POLL_FOR_MS
        ) {
          poll = setTimeout(fetchOnce, POLL_MS)
        }
      } catch {
        if (current)
          setState({ key, narrative: null, failed: true, slow: false })
      }
    }
    void fetchOnce()
    const slow = setTimeout(() => {
      if (current) {
        setState((s) =>
          s.key === key
            ? { ...s, slow: true }
            : { key, narrative: null, failed: false, slow: true }
        )
      }
    }, SLOW_MS)
    return () => {
      current = false
      clearTimeout(poll)
      clearTimeout(slow)
    }
  }, [key])

  return state.key === key
    ? state
    : { key, narrative: null, failed: false, slow: false }
}
