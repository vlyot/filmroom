import {
  createContext,
  use,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react"
import { toast } from "sonner"

import type { Match } from "@/contracts"
import { mmss, OUTCOME_LABELS, ZONE_LABELS } from "@/lib/format"
import { ReplayStore, type ReplaySnapshot } from "@/lib/replay/store"
import type { ReplayStream } from "@/lib/replay/types"
import { navigate } from "@/lib/router"
import { useActiveStyle, usePreferences } from "@/state/preferences"
import { useSource, useSourceState } from "@/state/source"

type ReplayContext = {
  store: ReplayStore
  match: Match
  play: () => void
  pause: () => void
  seek: (tMs: number) => void
  setSpeed: (speed: number) => void
}

const Context = createContext<ReplayContext | null>(null)
const RECONNECT_MS = 2000
const TOAST_WITHIN_MS = 15000

/** One replay stream for the match, kept open while the viewer moves between the match's pages. Changing the
 * preset, audience or language reconnects at the same clock; a dropped live stream falls back to the bundle
 * when the API is gone, and reconnects when it isn't. */
export function ReplayProvider({
  match,
  children,
}: {
  match: Match
  children: ReactNode
}) {
  const source = useSource()
  const { mode } = useSourceState()
  const { presetId } = useActiveStyle()
  const { audience, language } = usePreferences()
  const [store] = useState(() => new ReplayStore(match.duration_ms))
  const [attempt, setAttempt] = useState(0)
  const stream = useRef<ReplayStream | null>(null)

  useEffect(() => {
    const { playing, speed } = store.getSnapshot()
    const fromMs = store.timeAt(performance.now())
    const next = source.replay(match.id, {
      style: presetId,
      audience,
      language,
      speed,
      fromMs,
    })
    if (!playing) next.send({ action: "pause" })
    stream.current = next
    let retry: ReturnType<typeof setTimeout> | undefined
    const offMessage = next.onMessage((message) =>
      store.receive(message, performance.now())
    )
    const offLost = next.onLost(() => {
      void source.check().then(() => {
        if (source.getState().mode === "live")
          retry = setTimeout(() => setAttempt((a) => a + 1), RECONNECT_MS)
      })
    })
    return () => {
      clearTimeout(retry)
      offMessage()
      offLost()
      next.close()
      stream.current = null
    }
  }, [source, mode, store, match.id, presetId, audience, language, attempt])

  useEffect(
    () =>
      store.onNewFlag(({ summary }) => {
        const snapshot = store.getSnapshot()
        if (
          !snapshot.playing ||
          snapshot.tMs - summary.end_ms > TOAST_WITHIN_MS
        )
          return
        const team = match.teams[summary.team].name
        toast(`Flagged at ${mmss(summary.end_ms)}: ${team}`, {
          description: `${OUTCOME_LABELS[summary.outcome]} in the ${ZONE_LABELS[summary.ended_zone]}`,
          action: {
            label: "Open",
            onClick: () =>
              navigate({
                page: "possession",
                matchId: match.id,
                possessionId: summary.id,
              }),
          },
        })
      }),
    [store, match]
  )

  const value = useMemo<ReplayContext>(
    () => ({
      store,
      match,
      play: () => stream.current?.send({ action: "play" }),
      pause: () => stream.current?.send({ action: "pause" }),
      seek: (tMs) => stream.current?.send({ action: "seek", value: tMs }),
      setSpeed: (speed) =>
        stream.current?.send({ action: "speed", value: speed }),
    }),
    [store, match]
  )
  return <Context value={value}>{children}</Context>
}

export function useReplay(): ReplayContext {
  return use(Context)!
}

export function useReplaySnapshot(): ReplaySnapshot {
  const { store } = useReplay()
  return useSyncExternalStore(store.subscribe, store.getSnapshot)
}
