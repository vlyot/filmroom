import { useEffect, useState } from "react"
import { AlertCircleIcon } from "lucide-react"
import { toast } from "sonner"

import { useResource } from "@/hooks/use-resource"
import { href, useRoute } from "@/lib/router"
import { connectSource, type FallbackSource } from "@/lib/source/fallback"
import { PreferencesProvider } from "@/state/preferences"
import { SourceProvider, useSource, useSourceState } from "@/state/source"
import { ModeBadge } from "@/components/mode-badge"
import { StyleControls } from "@/components/style-controls"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Skeleton } from "@/components/ui/skeleton"
import { TooltipProvider } from "@/components/ui/tooltip"
import { HomePage } from "@/pages/home"
import { MatchLayout } from "@/pages/match-layout"
import { StatusPage } from "@/pages/status"

export function App() {
  const [source, setSource] = useState<FallbackSource | null>(null)
  useEffect(() => {
    void connectSource().then(setSource)
  }, [])
  useEffect(() => source?.watch(), [source])
  if (!source) return <Loading />
  return (
    <SourceProvider source={source}>
      <Lens />
    </SourceProvider>
  )
}

/** Styles and the lens come first: every verdict on every page is computed from them. */
function Lens() {
  const source = useSource()
  const { lost, restored } = useSourceState()
  // Not keyed on the mode: the API and the bundle serve the same styles, and re-keying would unmount the whole
  // app (and the replay's clock) whenever it switches between them.
  const lens = useResource("lens", () =>
    Promise.all([source.styles(), source.lens()])
  )

  useEffect(() => {
    if (lost)
      toast.warning("The live API stopped answering", {
        description: "Switched to the offline bundle.",
      })
  }, [lost])

  useEffect(() => {
    if (restored)
      toast.success("The live API is back", {
        description: "Switched back from the offline bundle.",
      })
  }, [restored])

  if (lens.status === "loading") return <Loading />
  if (lens.status === "error") {
    return (
      <main className="mx-auto max-w-3xl p-6">
        <Alert variant="destructive">
          <AlertCircleIcon />
          <AlertTitle>No match data found</AlertTitle>
          <AlertDescription>
            {lens.error.message}. Start the API, or export the bundle with
            scripts/export_bundle.py.
          </AlertDescription>
        </Alert>
      </main>
    )
  }
  const [styles, styleLens] = lens.data
  return (
    <PreferencesProvider styles={styles} lens={styleLens}>
      <TooltipProvider>
        <Shell />
      </TooltipProvider>
    </PreferencesProvider>
  )
}

function Shell() {
  const route = useRoute()
  return (
    <div className="min-h-svh">
      <header className="sticky top-0 z-20 border-b bg-background/90 backdrop-blur print:hidden">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 sm:px-6">
          <a
            href={href({ page: "home" })}
            className="flex flex-col leading-tight"
          >
            <span className="text-lg font-semibold tracking-tight">
              FilmRoom
            </span>
            <span className="text-xs text-muted-foreground">
              What was on, and not taken
            </span>
          </a>
          <div className="flex flex-1 flex-wrap items-center justify-end gap-2">
            <StyleControls />
            <ModeBadge />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6">
        {route.page === "home" ? (
          <HomePage />
        ) : route.page === "status" ? (
          <StatusPage />
        ) : (
          <MatchLayout route={route} />
        )}
      </main>
    </div>
  )
}

function Loading() {
  return (
    <main
      className="mx-auto flex max-w-3xl flex-col gap-4 p-6"
      aria-label="Loading"
    >
      <Skeleton className="h-10 w-48" />
      <Skeleton className="h-28 w-full rounded-xl" />
      <Skeleton className="h-28 w-full rounded-xl" />
    </main>
  )
}

export default App
