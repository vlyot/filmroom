import type { Match, Option } from "@/contracts"
import type { Judged } from "@/hooks/use-judged"
import { score } from "@/lib/lens"
import { actionPhrase, formatFact } from "@/lib/narrative"
import { cn } from "@/lib/utils"
import { useActiveStyle } from "@/state/preferences"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

export const BAND_BADGE: Record<Option["p_success_band"], string> = {
  high: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
  medium: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
  low: "bg-rose-500/15 text-rose-700 dark:text-rose-400",
}

/** Every option at the decision, ranked by its score under the active style. */
export function OptionsTable({
  judged,
  match,
  selectedId,
  onSelect,
}: {
  judged: Judged
  match: Match
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  const { style } = useActiveStyle()
  const ranked = [...judged.decision.options].sort(
    (a, b) => score(b, style) - score(a, style)
  )
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Option</TableHead>
          <TableHead>Success odds</TableHead>
          <TableHead className="text-right">Danger gain</TableHead>
          <TableHead className="text-right">Score</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {ranked.map((option) => {
          const chosen = option.id === judged.verdict.chosen_option_id
          const best = option.id === judged.verdict.best_option_id
          return (
            <TableRow
              key={option.id}
              data-state={option.id === selectedId ? "selected" : undefined}
              className="cursor-pointer"
              onClick={() => onSelect(option.id)}
            >
              <TableCell className="whitespace-normal">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className={cn(best && "font-medium")}>
                    {actionPhrase(option, match, "en")}
                  </span>
                  {chosen && <Badge variant="outline">chosen</Badge>}
                  {best && <Badge>best under {style.name}</Badge>}
                </div>
              </TableCell>
              <TableCell>
                <Badge className={BAND_BADGE[option.p_success_band]}>
                  {formatFact(
                    { value: option.p_success_band, kind: "band" },
                    "en"
                  )}{" "}
                  ·{" "}
                  {formatFact({ value: option.p_success, kind: "prob" }, "en")}
                </Badge>
              </TableCell>
              <TableCell className="text-right font-mono text-xs">
                {formatFact({ value: option.danger_gain, kind: "xt" }, "en")}
              </TableCell>
              <TableCell className="text-right font-mono text-xs">
                {score(option, style).toFixed(3)}
              </TableCell>
            </TableRow>
          )
        })}
      </TableBody>
    </Table>
  )
}
