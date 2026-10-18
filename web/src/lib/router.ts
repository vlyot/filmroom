// Hash routes, because GitHub Pages has no fallback to index.html for deep links.
import { useSyncExternalStore } from "react"

export type Route =
  | { page: "home" }
  | { page: "replay"; matchId: string }
  | { page: "possession"; matchId: string; possessionId: string }
  | { page: "pack"; matchId: string }
  | { page: "overlay"; matchId: string }

export function parseRoute(hash: string): Route {
  const parts = hash
    .replace(/^#\/?/, "")
    .split("/")
    .filter(Boolean)
    .map(decodeURIComponent)
  if (parts[0] !== "m" || !parts[1]) return { page: "home" }
  const matchId = parts[1]
  if (parts[2] === "p" && parts[3])
    return { page: "possession", matchId, possessionId: parts[3] }
  if (parts[2] === "pack") return { page: "pack", matchId }
  if (parts[2] === "overlay") return { page: "overlay", matchId }
  return { page: "replay", matchId }
}

export function href(route: Route): string {
  switch (route.page) {
    case "home":
      return "#/"
    case "replay":
      return `#/m/${encodeURIComponent(route.matchId)}`
    case "possession":
      return `#/m/${encodeURIComponent(route.matchId)}/p/${encodeURIComponent(route.possessionId)}`
    case "pack":
    case "overlay":
      return `#/m/${encodeURIComponent(route.matchId)}/${route.page}`
  }
}

export function navigate(route: Route) {
  window.location.hash = href(route)
}

const subscribe = (listener: () => void) => {
  window.addEventListener("hashchange", listener)
  return () => window.removeEventListener("hashchange", listener)
}

export function useRoute(): Route {
  const hash = useSyncExternalStore(subscribe, () => window.location.hash)
  return parseRoute(hash)
}
