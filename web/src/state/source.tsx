import { createContext, use, useSyncExternalStore, type ReactNode } from "react"

import type { FallbackSource, SourceState } from "@/lib/source/fallback"

const SourceContext = createContext<FallbackSource | null>(null)

export function SourceProvider({
  source,
  children,
}: {
  source: FallbackSource
  children: ReactNode
}) {
  return <SourceContext value={source}>{children}</SourceContext>
}

export function useSource(): FallbackSource {
  return use(SourceContext)!
}

export function useSourceState(): SourceState {
  const source = useSource()
  return useSyncExternalStore(source.subscribe, source.getState)
}
