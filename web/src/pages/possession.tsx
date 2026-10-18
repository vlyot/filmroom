import { lazy, Suspense, useEffect, useState } from "react"
import {
  AlertCircleIcon,
  ArrowLeftIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
} from "lucide-react"

import type { Match, Possession, PossessionSummary } from "@/contracts"
import { useJudged } from "@/hooks/use-judged"
import { useResource } from "@/hooks/use-resource"
import { mmss, OUTCOME_LABELS, ZONE_LABELS } from "@/lib/format"
import { href } from "@/lib/router"
import { cn } from "@/lib/utils"
import { useReplay } from "@/state/replay"
import { useSource, useSourceState } from "@/state/source"
import { FactorBreakdown } from "@/components/factor-breakdown"
import { NarrativeCard } from "@/components/narrative-card"
import { OptionsTable } from "@/components/options-table"
import { PossessionPitch } from "@/components/possession-pitch"
import { StyleCard } from "@/components/style-card"
import { VerdictLine } from "@/components/verdict-line"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

// Recharts is most of the bundle's weight and only this page draws a chart.
const DangerCurve = lazy(() =>
  import("@/components/danger-curve").then((m) => ({ default: m.DangerCurve }))
)

export function PossessionPage({
  match,
  possessions,
  possessionId,
}: {
  match: Match
  possessions: PossessionSummary[]
  possessionId: string
}) {
  const source = useSource()
  const { mode } = useSourceState()
  const { pause } = useReplay()
  const possession = useResource(`${mode}:${possessionId}`, () =>
    source.possession(possessionId)
  )

  useEffect(() => pause(), [pause, possessionId])

  const flagged = possessions.filter((p) => p.flagged)
  const index = flagged.findIndex((p) => p.id === possessionId)
  const neighbour = (step: number) => flagged[index + step]

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="ghost" asChild>
          <a href={href({ page: "replay", matchId: match.id })}>
            <ArrowLeftIcon />
            Replay
          </a>
        </Button>
        <div className="ml-auto flex gap-1">
          {[-1, 1].map((step) => {
            const other = neighbour(step)
            return (
              <Button
                key={step}
                size="sm"
                variant="outline"
                disabled={!other}
                asChild={Boolean(other)}
              >
                {other ? (
                  <a
                    href={href({
                      page: "possession",
                      matchId: match.id,
                      possessionId: other.id,
                    })}
                  >
                    {step < 0 ? <ChevronLeftIcon /> : null}
                    {step < 0 ? "Previous" : "Next"} flag
                    {step > 0 ? <ChevronRightIcon /> : null}
                  </a>
                ) : (
                  <span>{step < 0 ? "Previous" : "Next"} flag</span>
                )}
              </Button>
            )
          })}
        </div>
      </div>
      {possession.status === "loading" && (
        <Skeleton className="h-96 w-full rounded-xl" />
      )}
      {possession.status === "error" && (
        <Alert variant="destructive">
          <AlertCircleIcon />
          <AlertTitle>Possession not found</AlertTitle>
          <AlertDescription>{possession.error.message}</AlertDescription>
        </Alert>
      )}
      {possession.status === "ready" && (
        <Breakdown
          key={possession.data.id}
          possession={possession.data}
          match={match}
        />
      )}
    </div>
  )
}

function Breakdown({
  possession,
  match,
}: {
  possession: Possession
  match: Match
}) {
  const [decisionIdx, setDecisionIdx] = useState(
    possession.turning_point_idx ?? 0
  )
  const [selectedOptionId, setSelectedOptionId] = useState<string | null>(null)
  const judged = useJudged(possession, decisionIdx)
  const turningPoint = useJudged(possession)

  if (!judged || !turningPoint) {
    return (
      <Alert>
        <AlertTitle>Not flagged</AlertTitle>
        <AlertDescription>
          No option at this possession's final decision was clearly better, so
          FilmRoom doesn't flag it.
        </AlertDescription>
      </Alert>
    )
  }
  const tpPlayer = match.players.find(
    (p) => p.pid === turningPoint.decision.pid
  )
  const selectDecision = (idx: number) => {
    setDecisionIdx(idx)
    setSelectedOptionId(null)
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold">
            {mmss(turningPoint.decision.t_ms)} · {tpPlayer?.name} (
            {match.teams[possession.team].name})
          </h2>
          <Badge variant="outline">
            {OUTCOME_LABELS[possession.outcome]} in the{" "}
            {ZONE_LABELS[possession.ended_zone]}
          </Badge>
          <Badge variant="secondary">
            severity {possession.severity.toFixed(2)}
          </Badge>
        </div>
        <p className="text-sm text-muted-foreground">
          The turning point is where the move broke down: the possession's final
          decision.
        </p>
        <VerdictLine judged={turningPoint} match={match} />
      </div>
      <NarrativeCard possession={possession} match={match} />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader>
            <CardTitle>On the pitch</CardTitle>
            <CardDescription className="flex flex-wrap items-center gap-1.5">
              Decisions:
              {possession.decisions.map((d) => (
                <Button
                  key={d.idx}
                  size="xs"
                  variant={d.idx === decisionIdx ? "default" : "outline"}
                  className={cn(
                    d.is_turning_point && d.idx !== decisionIdx && "border-flag"
                  )}
                  onClick={() => selectDecision(d.idx)}
                >
                  {mmss(d.t_ms)} {d.kind}
                  {d.is_turning_point && " · turning point"}
                </Button>
              ))}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <PossessionPitch
              possession={possession}
              match={match}
              judged={judged}
              selectedOptionId={selectedOptionId}
              onSelectOption={setSelectedOptionId}
            />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>What was on</CardTitle>
            <CardDescription>
              Options at {mmss(judged.decision.t_ms)}, ranked under the active
              style. Pick one to compare it.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <OptionsTable
              judged={judged}
              match={match}
              selectedId={selectedOptionId}
              onSelect={setSelectedOptionId}
            />
          </CardContent>
        </Card>
      </div>
      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Danger across the possession</CardTitle>
            <CardDescription>
              Expected threat (xT) of where the ball was; lines mark the
              decisions.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Suspense fallback={<Skeleton className="h-44 w-full" />}>
              <DangerCurve
                possession={possession}
                selectedIdx={decisionIdx}
                onSelectDecision={selectDecision}
              />
            </Suspense>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Why, factor by factor</CardTitle>
            <CardDescription>
              Each factor's weight under the style times the difference between
              the options.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <FactorBreakdown
              judged={judged}
              match={match}
              selectedId={selectedOptionId}
            />
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Style card</CardTitle>
          <CardDescription>
            The principles behind the active style's weights, with their
            sources.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <StyleCard />
        </CardContent>
      </Card>
    </div>
  )
}
