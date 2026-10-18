import { EyeOffIcon } from "lucide-react"

import type { Match, Option } from "@/contracts"
import { cn } from "@/lib/utils"
import { positionOf, type Frame } from "@/lib/positions"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"

export const PITCH = { length: 110, width: 72 }
const BALL_PID = 128

export type Lane = {
  id: string
  from: [number, number]
  to: [number, number]
  band: Option["p_success_band"]
  chosen: boolean
  best: boolean
  selected: boolean
}

const BAND_STROKE: Record<Lane["band"], string> = {
  high: "stroke-emerald-500",
  medium: "stroke-amber-500",
  low: "stroke-rose-500",
}
const BAND_FILL: Record<Lane["band"], string> = {
  high: "fill-emerald-500",
  medium: "fill-amber-500",
  low: "fill-rose-500",
}

function Markings() {
  const { length: L, width: W } = PITCH
  const box = (depth: number, half: number, left: boolean) => (
    <rect
      x={left ? 0 : L - depth}
      y={W / 2 - half}
      width={depth}
      height={2 * half}
    />
  )
  return (
    <g className="fill-none stroke-foreground/25" strokeWidth={0.3}>
      <rect x={0} y={0} width={L} height={W} />
      <line x1={L / 2} y1={0} x2={L / 2} y2={W} />
      <circle cx={L / 2} cy={W / 2} r={9.15} />
      {box(16.5, 20.16, true)}
      {box(16.5, 20.16, false)}
      {box(5.5, 9.16, true)}
      {box(5.5, 9.16, false)}
      <rect x={-1.5} y={W / 2 - 3.66} width={1.5} height={7.32} />
      <rect x={L} y={W / 2 - 3.66} width={1.5} height={7.32} />
    </g>
  )
}

/** The pitch at one moment: players and ball from a positions frame, and option lanes when given. Team 0
 * attacks towards x = 110 in the data, and the pitch is drawn that way. */
export function Pitch({
  frame,
  match,
  lanes = [],
  focusPid,
  onSelectLane,
  className,
}: {
  frame: Frame | null
  match: Match
  lanes?: Lane[]
  focusPid?: number
  onSelectLane?: (id: string) => void
  className?: string
}) {
  const players = new Map(match.players.map((p) => [p.pid, p]))
  const ball = frame && positionOf(frame, BALL_PID)
  return (
    <svg
      viewBox={`-3 -3 ${PITCH.length + 6} ${PITCH.width + 6}`}
      className={cn(
        "w-full rounded-lg bg-emerald-700/10 dark:bg-emerald-400/5",
        className
      )}
      role="img"
      aria-label="Pitch"
    >
      <Markings />
      {lanes.map((lane) => (
        <g
          key={lane.id}
          className={cn(
            onSelectLane && "cursor-pointer",
            !lane.chosen && !lane.best && !lane.selected && "opacity-45"
          )}
          onClick={() => onSelectLane?.(lane.id)}
        >
          <line
            x1={lane.from[0]}
            y1={lane.from[1]}
            x2={lane.to[0]}
            y2={lane.to[1]}
            className={BAND_STROKE[lane.band]}
            strokeWidth={lane.selected || lane.best ? 0.9 : 0.5}
            strokeDasharray={lane.chosen || lane.best ? undefined : "1.2 0.8"}
            strokeLinecap="round"
          />
          <circle
            cx={lane.to[0]}
            cy={lane.to[1]}
            r={lane.best ? 1 : 0.7}
            className={BAND_FILL[lane.band]}
          />
          {lane.best && (
            <circle
              cx={lane.to[0]}
              cy={lane.to[1]}
              r={2}
              className={cn("fill-none", BAND_STROKE[lane.band])}
              strokeWidth={0.3}
            />
          )}
        </g>
      ))}
      {frame?.pids.map((pid) => {
        const player = players.get(pid)
        const at = positionOf(frame, pid)
        if (!player || !at) return null
        return (
          <g key={pid} transform={`translate(${at[0]} ${at[1]})`}>
            {pid === focusPid && (
              <circle
                r={2.3}
                className="fill-none stroke-foreground"
                strokeWidth={0.35}
              />
            )}
            <circle
              r={1.45}
              className={cn(
                player.team === 0 ? "fill-team-0" : "fill-team-1",
                player.role === "GK" && "stroke-foreground"
              )}
              strokeWidth={0.3}
            />
            <text
              y={0.5}
              textAnchor="middle"
              className="fill-white font-semibold select-none"
              fontSize={1.35}
            >
              {player.shirt}
            </text>
          </g>
        )
      })}
      {ball && (
        <circle
          cx={ball[0]}
          cy={ball[1]}
          r={0.75}
          className="fill-white stroke-neutral-900"
          strokeWidth={0.25}
        />
      )}
    </svg>
  )
}

export function PitchUnavailable() {
  return (
    <Empty className="aspect-[116/78] rounded-lg border bg-muted/30">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <EyeOffIcon />
        </EmptyMedia>
        <EmptyTitle>Positions not published</EmptyTitle>
        <EmptyDescription>
          This bundle leaves out player positions. The verdict, options and
          narrative still come from the engine.
        </EmptyDescription>
      </EmptyHeader>
    </Empty>
  )
}

export function TeamLegend({ match }: { match: Match }) {
  return (
    <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
      <span className="flex items-center gap-1.5">
        <span className="size-2.5 rounded-full bg-team-0" />
        {match.teams[0].name}
      </span>
      <span className="flex items-center gap-1.5">
        <span className="size-2.5 rounded-full bg-team-1" />
        {match.teams[1].name}
      </span>
    </div>
  )
}
