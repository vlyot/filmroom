import { PauseIcon, PlayIcon, RotateCcwIcon } from "lucide-react"

import { mmss } from "@/lib/format"
import { useReplay, useReplaySnapshot } from "@/state/replay"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"

const SPEEDS = [1, 2, 5, 10]

export function ReplayControls() {
  const { match, play, pause, setSpeed } = useReplay()
  const { tMs, speed, playing, ended } = useReplaySnapshot()
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button
        size="sm"
        onClick={playing ? pause : play}
        aria-label={
          playing ? "Pause" : ended ? "Replay from the start" : "Play"
        }
      >
        {playing ? <PauseIcon /> : ended ? <RotateCcwIcon /> : <PlayIcon />}
        {playing ? "Pause" : ended ? "Replay" : "Play"}
      </Button>
      <ToggleGroup
        type="single"
        variant="outline"
        size="sm"
        spacing={0}
        value={String(speed)}
        onValueChange={(value) => value && setSpeed(Number(value))}
        aria-label="Replay speed"
      >
        {SPEEDS.map((s) => (
          <ToggleGroupItem
            key={s}
            value={String(s)}
            className="px-2.5 font-mono text-xs"
          >
            {s}×
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      <span className="font-mono text-sm tabular-nums">
        {mmss(tMs)}{" "}
        <span className="text-muted-foreground">
          / {mmss(match.duration_ms)}
        </span>
      </span>
      {ended && <Badge variant="secondary">Full time</Badge>}
    </div>
  )
}
