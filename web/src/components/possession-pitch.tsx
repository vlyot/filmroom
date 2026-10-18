import { useEffect, useRef, useState } from "react"
import { CrosshairIcon, PauseIcon, PlayIcon } from "lucide-react"

import type { Match, PositionsChunk, Possession } from "@/contracts"
import type { Judged } from "@/hooks/use-judged"
import { useResource } from "@/hooks/use-resource"
import { mmss } from "@/lib/format"
import { chunkEndMs, frameAt, positionOf } from "@/lib/positions"
import { useSource, useSourceState } from "@/state/source"
import {
  Pitch,
  PitchUnavailable,
  TeamLegend,
  type Lane,
} from "@/components/pitch"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Slider } from "@/components/ui/slider"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"

const SPEEDS = [0.5, 1, 2]
const AT_DECISION_MS = 150

/** The possession replayed on the pitch. It opens paused at the decision, with its options drawn as lanes;
 * playing from the start stops there again. */
export function PossessionPitch(props: {
  possession: Possession
  match: Match
  judged: Judged
  selectedOptionId: string | null
  onSelectOption: (id: string) => void
}) {
  const source = useSource()
  const { mode } = useSourceState()
  const positions = useResource(`${mode}:${props.possession.id}`, () =>
    source.positions(props.possession.id)
  )
  if (positions.status === "loading")
    return <Skeleton className="aspect-[116/78] w-full rounded-lg" />
  if (positions.status === "error" || positions.data === null)
    return <PitchUnavailable />
  return (
    <Playback
      key={props.judged.decision.idx}
      chunk={positions.data}
      {...props}
    />
  )
}

function Playback({
  chunk,
  match,
  judged,
  selectedOptionId,
  onSelectOption,
}: {
  chunk: PositionsChunk
  match: Match
  judged: Judged
  selectedOptionId: string | null
  onSelectOption: (id: string) => void
}) {
  const { decision } = judged
  const start = chunk.t0_ms
  const end = chunkEndMs(chunk)
  const [t, setT] = useState(decision.t_ms)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const shown = useRef(t)

  useEffect(() => {
    shown.current = t
  }, [t])

  useEffect(() => {
    if (!playing) return
    let raf = 0
    let last = performance.now()
    const step = (now: number) => {
      const current = shown.current
      const next = Math.min(end, current + (now - last) * speed)
      last = now
      const crossed = current < decision.t_ms && next >= decision.t_ms
      shown.current = crossed ? decision.t_ms : next
      setT(shown.current)
      if (crossed || next >= end) setPlaying(false)
      else raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [playing, speed, end, decision.t_ms])

  const atDecision = !playing && Math.abs(t - decision.t_ms) < AT_DECISION_MS
  const decisionFrame = frameAt(chunk, decision.t_ms)
  const from =
    decisionFrame &&
    (positionOf(decisionFrame, decision.pid) ?? positionOf(decisionFrame, 128))
  const lanes: Lane[] =
    atDecision && from
      ? decision.options.flatMap((o) =>
          o.target_xy
            ? [
                {
                  id: o.id,
                  from,
                  to: o.target_xy,
                  band: o.p_success_band,
                  chosen: o.id === judged.verdict.chosen_option_id,
                  best: o.id === judged.verdict.best_option_id,
                  selected: o.id === selectedOptionId,
                },
              ]
            : []
        )
      : []

  return (
    <div className="flex flex-col gap-3">
      <Pitch
        frame={frameAt(chunk, t)}
        match={match}
        lanes={lanes}
        focusPid={decision.pid}
        onSelectLane={onSelectOption}
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={() => {
            if (!playing && t >= end) setT(start)
            setPlaying(!playing)
          }}
        >
          {playing ? <PauseIcon /> : <PlayIcon />}
          {playing ? "Pause" : "Play"}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            setPlaying(false)
            setT(decision.t_ms)
          }}
        >
          <CrosshairIcon />
          Decision
        </Button>
        <ToggleGroup
          type="single"
          size="sm"
          variant="outline"
          spacing={0}
          value={String(speed)}
          onValueChange={(v) => v && setSpeed(Number(v))}
          aria-label="Playback speed"
        >
          {SPEEDS.map((s) => (
            <ToggleGroupItem
              key={s}
              value={String(s)}
              className="px-2 font-mono text-xs"
            >
              {s}×
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <span className="ml-auto font-mono text-xs text-muted-foreground tabular-nums">
          {mmss(t)}
        </span>
      </div>
      <Slider
        value={[t]}
        min={start}
        max={end}
        step={100}
        onValueChange={([value]) => {
          setPlaying(false)
          setT(value)
        }}
        aria-label="Scrub the possession"
      />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <TeamLegend match={match} />
        {lanes.length > 0 && (
          <span className="text-xs text-muted-foreground">
            Lanes: solid = chosen or best · colour = success odds (green high,
            amber medium, red low)
          </span>
        )}
      </div>
    </div>
  )
}
