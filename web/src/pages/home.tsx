import { AlertCircleIcon } from "lucide-react"

import type { MatchSummary } from "@/contracts"
import { useResource } from "@/hooks/use-resource"
import { MODE_LABELS } from "@/lib/format"
import { href } from "@/lib/router"
import { useSource, useSourceState } from "@/state/source"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

export function HomePage() {
  const source = useSource()
  const { mode } = useSourceState()
  const matches = useResource(`${mode}:matches`, () => source.matches())
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Matches</h1>
        <p className="text-muted-foreground">
          Replay a match: FilmRoom flags each possession where a clearly better
          option was on, as it ends.
        </p>
      </div>
      {matches.status === "loading" && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Skeleton className="h-32 rounded-xl" />
          <Skeleton className="h-32 rounded-xl" />
        </div>
      )}
      {matches.status === "error" && (
        <Alert variant="destructive">
          <AlertCircleIcon />
          <AlertTitle>No matches</AlertTitle>
          <AlertDescription>{matches.error.message}</AlertDescription>
        </Alert>
      )}
      {matches.status === "ready" && (
        <div className="grid gap-4 sm:grid-cols-2">
          {matches.data.map((match) => (
            <MatchCard key={match.id} match={match} />
          ))}
        </div>
      )}
    </div>
  )
}

function MatchCard({ match }: { match: MatchSummary }) {
  const source = useSource()
  const { mode } = useSourceState()
  const possessions = useResource(`${mode}:possessions:${match.id}`, () =>
    source.possessions(match.id)
  )
  const flagged =
    possessions.status === "ready"
      ? possessions.data.filter((p) => p.flagged).length
      : null
  return (
    <a
      href={href({ page: "replay", matchId: match.id })}
      className="rounded-xl outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      <Card className="h-full transition-colors hover:bg-muted/40">
        <CardHeader>
          <CardTitle>{match.title}</CardTitle>
          <CardDescription>
            {MODE_LABELS[match.mode] && `${MODE_LABELS[match.mode]} · `}
            {Math.round(match.duration_ms / 60000)} min
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {flagged === null ? (
            <Skeleton className="h-5 w-24" />
          ) : (
            <Badge variant="secondary">
              {flagged} flagged {flagged === 1 ? "moment" : "moments"}
            </Badge>
          )}
          {possessions.status === "ready" && (
            <Badge variant="outline">
              {possessions.data.length} possessions
            </Badge>
          )}
        </CardContent>
      </Card>
    </a>
  )
}
