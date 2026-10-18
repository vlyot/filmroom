import { useState } from "react"
import { AlertCircleIcon, DownloadIcon, PrinterIcon } from "lucide-react"

import type { Match, SessionPack } from "@/contracts"
import { useResource } from "@/hooks/use-resource"
import { OUTCOME_LABELS, ZONE_LABELS } from "@/lib/format"
import { language, renderNarrative } from "@/lib/narrative"
import { download, momentTime, packMarkdown } from "@/lib/pack"
import { href } from "@/lib/router"
import { useActiveStyle, usePreferences } from "@/state/preferences"
import { useSource, useSourceState } from "@/state/source"
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
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty"
import { Spinner } from "@/components/ui/spinner"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"

/** The half-time or full-time pack: the team's top flagged moments grouped into themes, each narrated, and
 * how the other presets would judge them. Built by the session-pack workflow (or exported with the bundle). */
export function SessionPackPage({ match }: { match: Match }) {
  const source = useSource()
  const { mode } = useSourceState()
  const { presetId, isCustom } = useActiveStyle()
  const { audience, language: code, styles } = usePreferences()
  const [team, setTeam] = useState<0 | 1>(0)
  const [period, setPeriod] = useState<"half" | "full">("full")
  const query = { team, period, style: presetId, audience, language: code }
  const pack = useResource(`${mode}:${match.id}:${JSON.stringify(query)}`, () =>
    source.sessionPack(match.id, query)
  )
  const styleName = styles.find((s) => s.id === presetId)!.name

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-3 print:hidden">
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          spacing={0}
          value={String(team)}
          onValueChange={(v) => v && setTeam(Number(v) as 0 | 1)}
          aria-label="Team"
        >
          {match.teams.map((t) => (
            <ToggleGroupItem
              key={t.side}
              value={String(t.side)}
              className="px-3"
            >
              {t.name}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          spacing={0}
          value={period}
          onValueChange={(v) => v && setPeriod(v as "half" | "full")}
          aria-label="Period"
        >
          <ToggleGroupItem value="half" className="px-3">
            Half-time
          </ToggleGroupItem>
          <ToggleGroupItem value="full" className="px-3">
            Full-time
          </ToggleGroupItem>
        </ToggleGroup>
        {pack.status === "ready" && (
          <div className="ml-auto flex gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                download(
                  `filmroom-${match.id}-${match.teams[team].key}-${period}.md`,
                  packMarkdown(pack.data, match, styles),
                  "text/markdown"
                )
              }
            >
              <DownloadIcon />
              Download .md
            </Button>
            <Button size="sm" variant="outline" onClick={() => window.print()}>
              <PrinterIcon />
              Print
            </Button>
          </div>
        )}
      </div>
      {isCustom && (
        <p className="text-sm text-muted-foreground print:hidden">
          Session packs are built for presets, so this one uses {styleName}, the
          preset under your sliders.
        </p>
      )}
      {pack.status === "loading" && (
        <Card>
          <CardContent className="flex items-center gap-3 py-10 text-muted-foreground">
            <Spinner />
            Building the pack: ranking moments, grouping themes and narrating
            each one (up to about 40 s live).
          </CardContent>
        </Card>
      )}
      {pack.status === "error" && (
        <Alert variant="destructive">
          <AlertCircleIcon />
          <AlertTitle>No session pack</AlertTitle>
          <AlertDescription>{pack.error.message}</AlertDescription>
        </Alert>
      )}
      {pack.status === "ready" && (
        <PackView pack={pack.data} match={match} styleName={styleName} />
      )}
    </div>
  )
}

function PackView({
  pack,
  match,
  styleName,
}: {
  pack: SessionPack
  match: Match
  styleName: string
}) {
  const factors = language("en").factors
  if (pack.moments.length === 0) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyTitle>Nothing to show</EmptyTitle>
          <EmptyDescription>
            {match.teams[pack.team].name} had no flagged moments in this period.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-lg font-semibold">
          {match.teams[pack.team].name}:{" "}
          {pack.period === "half" ? "half-time" : "full-time"} session
        </h2>
        <p className="text-sm text-muted-foreground">
          Judged under {styleName}, written for the {pack.audience}
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {pack.themes.map((theme) => (
          <Card key={theme.title}>
            <CardHeader>
              <CardTitle className="flex flex-wrap items-center gap-2">
                {theme.title}
                {theme.status === "fallback" && (
                  <Badge variant="outline">grouped by outcome</Badge>
                )}
              </CardTitle>
              <CardDescription>{theme.summary}</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-1.5">
              {pack.moments
                .filter((m) => theme.possession_ids.includes(m.summary.id))
                .map((m) => (
                  <Badge key={m.summary.id} variant="secondary">
                    #{m.rank} · {momentTime(m)}
                  </Badge>
                ))}
            </CardContent>
          </Card>
        ))}
      </div>
      <div className="flex flex-col gap-3">
        {pack.moments.map((moment) => (
          <Card key={moment.summary.id} className="break-inside-avoid">
            <CardHeader>
              <CardTitle className="flex flex-wrap items-center gap-2 text-base">
                <span>#{moment.rank}</span>
                <a
                  className="underline-offset-4 hover:underline"
                  href={href({
                    page: "possession",
                    matchId: match.id,
                    possessionId: moment.summary.id,
                  })}
                >
                  {momentTime(moment)} ·{" "}
                  {OUTCOME_LABELS[moment.summary.outcome]} in the{" "}
                  {ZONE_LABELS[moment.summary.ended_zone]}
                </a>
                <Badge
                  variant={
                    moment.narrative.status === "verified"
                      ? "default"
                      : "outline"
                  }
                >
                  {moment.narrative.status === "verified"
                    ? "verified"
                    : "template"}
                </Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p lang={moment.narrative.language}>
                {renderNarrative(
                  moment.narrative.template,
                  moment.narrative.facts,
                  moment.narrative.language
                )}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>
      {pack.style_shifts.length > 0 && (
        <Card className="break-inside-avoid">
          <CardHeader>
            <CardTitle>Under other styles</CardTitle>
            <CardDescription>
              How many of these moments each preset would judge differently, and
              why.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Style</TableHead>
                  <TableHead className="text-right">
                    Judged differently
                  </TableHead>
                  <TableHead>Mostly because of</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pack.style_shifts.map((shift) => (
                  <TableRow key={shift.style_id}>
                    <TableCell>{shift.name}</TableCell>
                    <TableCell className="text-right font-mono text-xs">
                      {shift.changed} of {pack.moments.length}
                    </TableCell>
                    <TableCell>
                      {shift.factor ? factors[shift.factor] : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
