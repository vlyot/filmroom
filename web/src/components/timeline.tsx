import { useState } from "react"

import type { PossessionSummary } from "@/contracts"
import { mmss, OUTCOME_LABELS, ZONE_LABELS } from "@/lib/format"
import { href } from "@/lib/router"
import { cn } from "@/lib/utils"
import { useReplay, useReplaySnapshot } from "@/state/replay"
import { Slider } from "@/components/ui/slider"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

/** The match so far: each possession that has closed, in its team's colour, and each flag where it was
 * raised, sized by severity. The slider below seeks. */
export function Timeline({
  possessions,
}: {
  possessions: PossessionSummary[]
}) {
  const { match, seek } = useReplay()
  const { tMs, flags } = useReplaySnapshot()
  const [dragging, setDragging] = useState<number | null>(null)
  const at = (ms: number) => `${(ms / match.duration_ms) * 100}%`
  const shown = flags.filter((f) => f.summary.end_ms <= tMs)

  return (
    <div className="flex flex-col gap-3">
      <div
        className="relative h-9 rounded-md bg-muted/60"
        aria-label="Match timeline"
      >
        {possessions
          .filter((p) => p.end_ms <= tMs)
          .map((p) => (
            <div
              key={p.id}
              className={cn(
                "absolute top-3.5 h-2",
                p.team === 0 ? "bg-team-0/50" : "bg-team-1/50"
              )}
              style={{
                left: at(p.start_ms),
                width: at(Math.max(p.end_ms - p.start_ms, 300)),
              }}
            />
          ))}
        {shown.map(({ summary }) => {
          const size = 10 + 8 * summary.severity
          return (
            <Tooltip key={summary.id}>
              <TooltipTrigger asChild>
                <a
                  href={href({
                    page: "possession",
                    matchId: match.id,
                    possessionId: summary.id,
                  })}
                  className="absolute top-1/2 -translate-1/2 rounded-full bg-flag ring-2 ring-background transition-transform hover:scale-125"
                  style={{
                    left: at(summary.end_ms),
                    width: size,
                    height: size,
                  }}
                  aria-label={`Flagged moment at ${mmss(summary.end_ms)}`}
                />
              </TooltipTrigger>
              <TooltipContent>
                {mmss(summary.end_ms)} · {match.teams[summary.team].name} ·{" "}
                {OUTCOME_LABELS[summary.outcome]} in the{" "}
                {ZONE_LABELS[summary.ended_zone]}
              </TooltipContent>
            </Tooltip>
          )
        })}
        <div
          className="absolute inset-y-0 w-0.5 bg-foreground"
          style={{ left: at(tMs) }}
        />
      </div>
      <Slider
        value={[dragging ?? tMs]}
        max={match.duration_ms}
        step={1000}
        onValueChange={([value]) => setDragging(value)}
        onValueCommit={([value]) => {
          setDragging(null)
          seek(value)
        }}
        aria-label="Seek"
      />
    </div>
  )
}
