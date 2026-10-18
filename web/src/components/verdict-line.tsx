import { ArrowRightLeftIcon } from "lucide-react"

import type { Match } from "@/contracts"
import type { Judged } from "@/hooks/use-judged"
import { flipLine } from "@/lib/lens"
import { actionPhrase, formatFact, language } from "@/lib/narrative"
import { useActiveStyle, usePreferences } from "@/state/preferences"

const UI_LANGUAGE = "en"

/** What the active style says about the decision, and why it differs from the reference when it does. */
export function VerdictLine({
  judged,
  match,
  compact = false,
}: {
  judged: Judged
  match: Match
  compact?: boolean
}) {
  const { style, reference } = useActiveStyle()
  const { lens } = usePreferences()
  const options = new Map(judged.decision.options.map((o) => [o.id, o]))
  const best = options.get(judged.verdict.best_option_id)!
  const chosen = options.get(judged.verdict.chosen_option_id)!
  const reason = judged.verdict.flip_reason
  const odds = formatFact(
    { value: best.p_success_band, kind: "band" },
    UI_LANGUAGE
  )
  const gain = formatFact({ value: best.danger_gain, kind: "xt" }, UI_LANGUAGE)
  return (
    <div className="flex flex-col gap-1">
      <p className={compact ? "text-sm" : "text-base font-medium"}>
        {judged.verdict.better_available ? (
          <>
            Better under {style.name}: {actionPhrase(best, match, UI_LANGUAGE)}{" "}
            <span className="text-muted-foreground">
              ({odds} odds, {gain})
            </span>
          </>
        ) : (
          <>
            Under {style.name}, {actionPhrase(chosen, match, UI_LANGUAGE)} was
            the best option
          </>
        )}
      </p>
      {reason && (
        <p className="flex items-start gap-1.5 text-sm text-amber-700 dark:text-amber-400">
          <ArrowRightLeftIcon className="mt-0.5 size-3.5 shrink-0" />
          <span>
            Verdict changed:{" "}
            {flipLine(
              reason,
              style,
              reference,
              lens,
              language(UI_LANGUAGE).factors[reason.factor]
            )}
          </span>
        </p>
      )}
    </div>
  )
}
