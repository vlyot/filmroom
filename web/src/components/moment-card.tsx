import { ChevronRightIcon } from "lucide-react"

import type { Match, PossessionSummary } from "@/contracts"
import { useJudged } from "@/hooks/use-judged"
import { useResource } from "@/hooks/use-resource"
import { mmss, OUTCOME_LABELS, ZONE_LABELS } from "@/lib/format"
import { href } from "@/lib/router"
import { usePreferences } from "@/state/preferences"
import { useSource, useSourceState } from "@/state/source"
import { VerdictLine } from "@/components/verdict-line"
import { Badge } from "@/components/ui/badge"
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemTitle,
} from "@/components/ui/item"
import { Skeleton } from "@/components/ui/skeleton"

/** One flagged moment: when, who, how it ended and the verdict under the active style. With the player
 * audience and a player chosen, only that player's moments are shown. */
export function MomentCard({
  summary,
  match,
}: {
  summary: PossessionSummary
  match: Match
}) {
  const source = useSource()
  const { mode } = useSourceState()
  const { audience, playerPid } = usePreferences()
  const possession = useResource(`${mode}:${summary.id}`, () =>
    source.possession(summary.id)
  )
  const data = possession.status === "ready" ? possession.data : null
  const judged = useJudged(data)

  if (
    audience === "player" &&
    playerPid !== null &&
    judged &&
    judged.decision.pid !== playerPid
  )
    return null
  const player =
    judged && match.players.find((p) => p.pid === judged.decision.pid)
  return (
    <Item variant="outline" asChild>
      <a
        href={href({
          page: "possession",
          matchId: match.id,
          possessionId: summary.id,
        })}
      >
        <ItemContent className="gap-1.5">
          <ItemTitle className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-muted-foreground">
              {mmss(judged?.decision.t_ms ?? summary.end_ms)}
            </span>
            <span>{match.teams[summary.team].name}</span>
            <Badge variant="outline">
              {OUTCOME_LABELS[summary.outcome]} ·{" "}
              {ZONE_LABELS[summary.ended_zone]}
            </Badge>
            {judged?.verdict.flip_reason && (
              <Badge variant="secondary">Verdict changed</Badge>
            )}
          </ItemTitle>
          {judged ? (
            <div className="flex flex-col gap-0.5 text-sm text-muted-foreground">
              {player && <span className="text-foreground">{player.name}</span>}
              <VerdictLine judged={judged} match={match} compact />
            </div>
          ) : possession.status === "error" ? (
            <ItemDescription>Couldn't load this moment.</ItemDescription>
          ) : (
            <Skeleton className="h-4 w-2/3" />
          )}
        </ItemContent>
        <ItemActions className="flex-col items-end gap-1">
          <span className="text-xs text-muted-foreground">
            severity {summary.severity.toFixed(2)}
          </span>
          <ChevronRightIcon className="size-4 text-muted-foreground" />
        </ItemActions>
      </a>
    </Item>
  )
}
