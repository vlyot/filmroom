import { useEffect, useState } from "react"
import { AlertCircleIcon } from "lucide-react"

import type {
  BundleManifest,
  MatchSummary,
  PossessionSummary,
} from "@/contracts"
import { loadManifest, loadMatches, loadPossessions } from "@/lib/bundle"
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

type MatchRow = { match: MatchSummary; possessions: PossessionSummary[] }
type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; manifest: BundleManifest; rows: MatchRow[] }

async function loadBundle(): Promise<State> {
  const [manifest, matches] = await Promise.all([loadManifest(), loadMatches()])
  const rows = await Promise.all(
    matches.map(async (match) => ({
      match,
      possessions: await loadPossessions(match.id),
    }))
  )
  return { status: "ready", manifest, rows }
}

export function App() {
  const [state, setState] = useState<State>({ status: "loading" })

  useEffect(() => {
    let cancelled = false
    loadBundle()
      .catch((error: unknown): State => ({
        status: "error",
        message: error instanceof Error ? error.message : String(error),
      }))
      .then((next) => {
        if (!cancelled) setState(next)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <main className="mx-auto flex min-h-svh max-w-3xl flex-col gap-6 p-6">
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">FilmRoom</h1>
          {state.status === "ready" && (
            <>
              <Badge variant="secondary">
                contract v{state.manifest.contract_version}
              </Badge>
              <Badge variant="outline">
                {state.manifest.public ? "public bundle" : "full bundle"}
              </Badge>
            </>
          )}
        </div>
        <p className="text-sm text-muted-foreground">
          What was on, and not taken.
        </p>
      </header>

      {state.status === "loading" && (
        <div className="flex flex-col gap-4" aria-label="Loading matches">
          <Skeleton className="h-28 w-full rounded-xl" />
          <Skeleton className="h-28 w-full rounded-xl" />
        </div>
      )}

      {state.status === "error" && (
        <Alert variant="destructive">
          <AlertCircleIcon />
          <AlertTitle>No match data found</AlertTitle>
          <AlertDescription>
            {state.message}. Export the bundle with scripts/export_bundle.py.
          </AlertDescription>
        </Alert>
      )}

      {state.status === "ready" &&
        state.rows.map(({ match, possessions }) => (
          <Card key={match.id}>
            <CardHeader>
              <CardTitle>{match.title}</CardTitle>
              <CardDescription>
                {match.mode.replaceAll("_", " ")} ·{" "}
                {Math.round(match.duration_ms / 60000)} min
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-wrap items-center gap-2 text-sm">
              <span>
                {possessions.length} flagged{" "}
                {possessions.length === 1 ? "possession" : "possessions"}
              </span>
              {possessions.map((p) => (
                <Badge key={p.id} variant="outline">
                  {p.outcome.replaceAll("_", " ")} · {p.ended_zone}
                </Badge>
              ))}
            </CardContent>
          </Card>
        ))}
    </main>
  )
}

export default App
