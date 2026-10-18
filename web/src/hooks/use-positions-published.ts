import { useResource } from "@/hooks/use-resource"
import { useSource, useSourceState } from "@/state/source"

/** Whether player positions are available: always from the API; from the bundle unless it was exported
 * public (positions left out). Undefined while that is being checked. */
export function usePositionsPublished(): boolean | undefined {
  const source = useSource()
  const { mode } = useSourceState()
  const manifest = useResource(mode === "offline" ? "manifest" : null, () =>
    source.bundle.manifest()
  )
  if (mode === "live") return true
  return manifest.status === "ready" ? !manifest.data.public : undefined
}
