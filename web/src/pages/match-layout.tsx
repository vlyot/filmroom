import { AlertCircleIcon, ArrowLeftIcon } from "lucide-react"

import type { Match, PossessionSummary } from "@/contracts"
import { useResource } from "@/hooks/use-resource"
import { href, navigate, type Route } from "@/lib/router"
import { ReplayProvider } from "@/state/replay"
import { useSource } from "@/state/source"
import { AnalystSheet } from "@/components/analyst-sheet"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { OverlayPage } from "@/pages/overlay"
import { PossessionPage } from "@/pages/possession"
import { ReplayPage } from "@/pages/replay"
import { SessionPackPage } from "@/pages/session-pack"

type MatchRoute = Exclude<Route, { page: "home" }>

export type MatchData = { match: Match; possessions: PossessionSummary[] }

/** One match: its replay stream stays open across the replay, breakdown, session pack and overlay pages. */
export function MatchLayout({ route }: { route: MatchRoute }) {
  const source = useSource()
  // Not keyed on the mode: the API and the bundle hold the same match, and re-keying would remount the
  // replay and lose its clock when the app falls back.
  const data = useResource(`match:${route.matchId}`, async () => {
    const [match, possessions] = await Promise.all([
      source.match(route.matchId),
      source.possessions(route.matchId),
    ])
    return { match, possessions }
  })

  if (data.status === "loading")
    return <Skeleton className="h-96 w-full rounded-xl" />
  if (data.status === "error") {
    return (
      <Alert variant="destructive">
        <AlertCircleIcon />
        <AlertTitle>Match not found</AlertTitle>
        <AlertDescription>{data.error.message}</AlertDescription>
      </Alert>
    )
  }
  const { match, possessions } = data.data
  const tab = route.page === "possession" ? "replay" : route.page
  return (
    <ReplayProvider key={match.id} match={match}>
      <div className="flex flex-col gap-6">
        <div className="flex flex-wrap items-center gap-3">
          <Button size="icon" variant="ghost" asChild aria-label="All matches">
            <a href={href({ page: "home" })}>
              <ArrowLeftIcon />
            </a>
          </Button>
          <h1 className="text-xl font-semibold tracking-tight">
            {match.title}
          </h1>
          <Tabs
            value={tab}
            onValueChange={(page) =>
              navigate({
                page: page as "replay" | "pack" | "overlay",
                matchId: match.id,
              })
            }
          >
            <TabsList>
              <TabsTrigger value="replay">Replay</TabsTrigger>
              <TabsTrigger value="pack">Session pack</TabsTrigger>
              <TabsTrigger value="overlay">Overlay feed</TabsTrigger>
            </TabsList>
          </Tabs>
          <div className="ml-auto">
            <AnalystSheet match={match} possessions={possessions} />
          </div>
        </div>
        {route.page === "replay" && (
          <ReplayPage match={match} possessions={possessions} />
        )}
        {route.page === "possession" && (
          <PossessionPage
            match={match}
            possessions={possessions}
            possessionId={route.possessionId}
          />
        )}
        {route.page === "pack" && <SessionPackPage match={match} />}
        {route.page === "overlay" && <OverlayPage match={match} />}
      </div>
    </ReplayProvider>
  )
}
