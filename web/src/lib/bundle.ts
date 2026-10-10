import type {
  BundleManifest,
  MatchSummary,
  PossessionSummary,
} from "@/contracts"

const BASE = `${import.meta.env.BASE_URL}bundle/`

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(BASE + path)
  // Dev servers answer missing files with index.html, so a 200 is not enough.
  const isJson = response.headers.get("content-type")?.includes("json")
  if (!response.ok || !isJson) throw new Error(`${path} not found`)
  return (await response.json()) as T
}

export const loadManifest = () => getJson<BundleManifest>("manifest.json")
export const loadMatches = () => getJson<MatchSummary[]>("matches.json")
export const loadPossessions = (matchId: string) =>
  getJson<PossessionSummary[]>(`matches/${matchId}/possessions.json`)
