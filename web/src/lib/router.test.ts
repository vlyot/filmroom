import { describe, expect, it } from "vitest"

import { href, parseRoute, type Route } from "@/lib/router"

describe("router", () => {
  it("parses every page and round-trips through href", () => {
    const routes: Route[] = [
      { page: "home" },
      { page: "replay", matchId: "2019_09_09_001" },
      {
        page: "possession",
        matchId: "2019_09_09_001",
        possessionId: "2019_09_09_001-17196",
      },
      { page: "pack", matchId: "m" },
      { page: "overlay", matchId: "m" },
    ]
    for (const route of routes) expect(parseRoute(href(route))).toEqual(route)
  })

  it("falls back to home for unknown hashes and decodes params", () => {
    expect(parseRoute("")).toEqual({ page: "home" })
    expect(parseRoute("#/nowhere")).toEqual({ page: "home" })
    expect(parseRoute("#/m/a%20b")).toEqual({ page: "replay", matchId: "a b" })
  })
})
