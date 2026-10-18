import { useEffect, useState } from "react"

import type { Frame } from "@/lib/positions"
import { useReplay } from "@/state/replay"
import { Pitch, PitchUnavailable, TeamLegend } from "@/components/pitch"
import { usePositionsPublished } from "@/hooks/use-positions-published"

/** The replay's pitch: positions interpolated on every animation frame from the stream's one-second
 * slices, holding the last frame between possessions. */
export function LivePitch() {
  const { store, match } = useReplay()
  const published = usePositionsPublished()
  const [frame, setFrame] = useState<Frame | null>(null)

  useEffect(() => {
    let raf = 0
    let shownAt = Number.NaN
    const draw = () => {
      const t = store.timeAt(performance.now())
      if (t !== shownAt) {
        const next = store.frameAt(t)
        if (next) {
          shownAt = t
          setFrame(next)
        }
      }
      raf = requestAnimationFrame(draw)
    }
    raf = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(raf)
  }, [store])

  if (published === false) return <PitchUnavailable />
  return (
    <div className="flex flex-col gap-2">
      <Pitch frame={frame} match={match} />
      <TeamLegend match={match} />
    </div>
  )
}
