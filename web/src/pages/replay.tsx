import { FlagIcon } from "lucide-react"

import type { Match, PossessionSummary } from "@/contracts"
import { usePreferences } from "@/state/preferences"
import { useReplaySnapshot } from "@/state/replay"
import { LivePitch } from "@/components/live-pitch"
import { MomentCard } from "@/components/moment-card"
import { ReplayControls } from "@/components/replay-controls"
import { Timeline } from "@/components/timeline"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

const EVERYONE = "everyone"

export function ReplayPage({
  match,
  possessions,
}: {
  match: Match
  possessions: PossessionSummary[]
}) {
  const { tMs, flags } = useReplaySnapshot()
  const shown = flags.filter((f) => f.summary.end_ms <= tMs).reverse()
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_400px]">
      <div className="flex flex-col gap-4">
        <LivePitch />
        <ReplayControls />
        <Timeline possessions={possessions} />
      </div>
      <Card className="lg:max-h-[calc(100svh-10rem)]">
        <CardHeader>
          <CardTitle>Flagged so far ({shown.length})</CardTitle>
          <CardDescription>
            Newest first, judged under the style you pick above.
          </CardDescription>
          <PlayerFilter match={match} />
        </CardHeader>
        <CardContent className="min-h-0 flex-1">
          {shown.length === 0 ? (
            <Empty>
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <FlagIcon />
                </EmptyMedia>
                <EmptyTitle>No flags yet</EmptyTitle>
                <EmptyDescription>
                  Press play. Each possession is analysed as it ends, and the
                  ones where a clearly better option was on appear here.
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <ScrollArea className="h-full max-h-[60svh] lg:max-h-none">
              <div className="flex flex-col gap-2 pr-3">
                {shown.map((f) => (
                  <MomentCard
                    key={f.summary.id}
                    summary={f.summary}
                    match={match}
                  />
                ))}
              </div>
            </ScrollArea>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

/** With the player audience, show one player's moments only. */
function PlayerFilter({ match }: { match: Match }) {
  const { audience, playerPid, set } = usePreferences()
  if (audience !== "player") return null
  const players = [...match.players].sort(
    (a, b) => a.team - b.team || a.shirt - b.shirt
  )
  return (
    <Select
      value={playerPid === null ? EVERYONE : String(playerPid)}
      onValueChange={(value) =>
        set({ playerPid: value === EVERYONE ? null : Number(value) })
      }
    >
      <SelectTrigger size="sm" className="w-full" aria-label="Player">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={EVERYONE}>Every player</SelectItem>
        {players.map((p) => (
          <SelectItem key={p.pid} value={String(p.pid)}>
            {p.shirt} · {p.name} ({match.teams[p.team].name})
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
