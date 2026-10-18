import { language } from "@/lib/narrative"
import { useActiveStyle, usePreferences } from "@/state/preferences"
import { Badge } from "@/components/ui/badge"

/** The active style's principles: what each rule set asks for, the engine factor it moves and its source. */
export function StyleCard() {
  const { style, isCustom } = useActiveStyle()
  const { lens } = usePreferences()
  const factors = language("en").factors
  const ruleSets = [style.with_ball, style.without_ball].map((id) =>
    lens.rule_sets.find((r) => r.id === id)!
  )
  return (
    <div className="flex flex-col gap-4 text-sm">
      {isCustom && (
        <p className="text-muted-foreground">
          Custom sliders on top of the {ruleSets.map((r) => r.name).join(" + ")}{" "}
          principles.
        </p>
      )}
      {ruleSets.map((ruleSet) => (
        <div key={ruleSet.id} className="flex flex-col gap-2">
          <h4 className="font-medium">
            {ruleSet.name}{" "}
            <span className="font-normal text-muted-foreground">
              {ruleSet.axis === "with_ball"
                ? "with the ball"
                : "without the ball"}
            </span>
          </h4>
          <ul className="flex flex-col gap-2">
            {ruleSet.principles.map((p) => (
              <li key={p.text} className="flex flex-col gap-0.5">
                <span>
                  {p.text} <Badge variant="outline">{factors[p.factor]}</Badge>
                </span>
                <span className="text-xs text-muted-foreground">
                  {p.source}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}
