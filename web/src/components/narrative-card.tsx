import { BadgeCheckIcon } from "lucide-react"

import type { Match, Possession } from "@/contracts"
import { useNarrative } from "@/hooks/use-narrative"
import { language } from "@/lib/narrative"
import { useActiveStyle, usePreferences } from "@/state/preferences"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Spinner } from "@/components/ui/spinner"

/** The explanation, template first: every number in it is a slot filled from the engine's facts. */
export function NarrativeCard({
  possession,
  match,
}: {
  possession: Possession
  match: Match
}) {
  const narrative = useNarrative(possession, match)
  const { audience, language: code } = usePreferences()
  const { isCustom } = useActiveStyle()
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          Explanation
          <Status status={narrative.status} slow={narrative.slow} />
        </CardTitle>
        <CardDescription>
          For the {audience}, in {language(code).name}
          {isCustom &&
            " · custom sliders get the template, which states the same verdict"}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <p className="text-base leading-relaxed" lang={code}>
          {narrative.text}
        </p>
      </CardContent>
    </Card>
  )
}

function Status({ status, slow }: { status: string; slow: boolean }) {
  if (status === "verified") {
    return (
      <Badge className="bg-emerald-500/15 text-emerald-700 dark:text-emerald-400">
        <BadgeCheckIcon />
        Verified
      </Badge>
    )
  }
  if (status === "pending") {
    return (
      <Badge variant="secondary">
        <Spinner />
        {slow ? "Full narrative pending" : "Writing…"}
      </Badge>
    )
  }
  return (
    <Badge variant="outline">
      {status === "failed" ? "Template (generation gave up)" : "Template"}
    </Badge>
  )
}
