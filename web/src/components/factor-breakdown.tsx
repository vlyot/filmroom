import type { Match, Option } from "@/contracts"
import type { Judged } from "@/hooks/use-judged"
import { score } from "@/lib/lens"
import { actionPhrase, language } from "@/lib/narrative"
import { cn } from "@/lib/utils"
import { useActiveStyle, usePreferences } from "@/state/preferences"
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

/** The other option to set against the chosen one: the selected option, else the best under the style,
 * else (when the choice was best) the runner-up. */
function comparedOption(
  judged: Judged,
  selectedId: string | null,
  rank: (o: Option) => number
): Option | null {
  const { options } = judged.decision
  const chosenId = judged.verdict.chosen_option_id
  if (selectedId && selectedId !== chosenId)
    return options.find((o) => o.id === selectedId)!
  if (judged.verdict.better_available)
    return options.find((o) => o.id === judged.verdict.best_option_id)!
  return (
    [...options]
      .filter((o) => o.id !== chosenId)
      .sort((a, b) => rank(b) - rank(a))[0] ?? null
  )
}

/** Why one option outscores the other under the style: each factor's weight times the difference in that
 * factor. The factor behind a verdict change is highlighted. */
export function FactorBreakdown({
  judged,
  match,
  selectedId,
}: {
  judged: Judged
  match: Match
  selectedId: string | null
}) {
  const { style } = useActiveStyle()
  const { lens } = usePreferences()
  const chosen = judged.decision.options.find(
    (o) => o.id === judged.verdict.chosen_option_id
  )!
  const other = comparedOption(judged, selectedId, (o) => score(o, style))
  if (!other) return null
  const labels = language("en").factors
  const flipFactor = judged.verdict.flip_reason?.factor
  const rows = Object.keys(lens.base).map((factor) => {
    const weight = style.weights[factor] ?? 0
    const a = chosen.factors[factor] ?? 0
    const b = other.factors[factor] ?? 0
    return { factor, weight, a, b, delta: weight * (b - a) }
  })
  const total = score(other, style) - score(chosen, style)
  const signed = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(3)}`
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Factor</TableHead>
          <TableHead className="text-right">Weight</TableHead>
          <TableHead className="text-right">Chosen</TableHead>
          <TableHead className="text-right whitespace-normal">
            {actionPhrase(other, match, "en")}
          </TableHead>
          <TableHead className="text-right">Difference</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow
            key={row.factor}
            className={cn(row.factor === flipFactor && "bg-amber-500/10")}
          >
            <TableCell>{labels[row.factor]}</TableCell>
            <TableCell className="text-right font-mono text-xs">
              {row.weight.toFixed(2)}
            </TableCell>
            <TableCell className="text-right font-mono text-xs">
              {row.a.toFixed(2)}
            </TableCell>
            <TableCell className="text-right font-mono text-xs">
              {row.b.toFixed(2)}
            </TableCell>
            <TableCell
              className={cn(
                "text-right font-mono text-xs",
                row.delta > 0.0005 && "text-emerald-700 dark:text-emerald-400",
                row.delta < -0.0005 && "text-rose-700 dark:text-rose-400"
              )}
            >
              {signed(row.delta)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
      <TableFooter>
        <TableRow>
          <TableCell colSpan={4}>Score difference under {style.name}</TableCell>
          <TableCell className="text-right font-mono text-xs">
            {signed(total)}
          </TableCell>
        </TableRow>
      </TableFooter>
    </Table>
  )
}
