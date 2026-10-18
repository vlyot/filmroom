import { afterEach, describe, expect, it, vi } from "vitest"

import { ApiSource } from "@/lib/source/api"
import { BundleSource, bundlePath } from "@/lib/source/bundle"
import { FallbackSource } from "@/lib/source/fallback"

const HEALTH = {
  status: "ok",
  contract_version: "0.5.0",
  source: "engine",
  llm: true,
} as const
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  })

afterEach(() => vi.unstubAllGlobals())

describe("bundle paths", () => {
  it("mirror the exporter's route_to_path", () => {
    expect(bundlePath("/matches")).toBe("matches.json")
    expect(bundlePath("/possessions/a-1/positions")).toBe(
      "possessions/a-1/positions.json"
    )
    expect(
      bundlePath("/possessions/a-1/narrative", {
        style: "s",
        audience: "fan",
        language: "es",
      })
    ).toBe("possessions/a-1/narrative/s.fan.es.json")
    const pack = {
      team: 1,
      period: "half",
      style: "s",
      audience: "coach",
      language: "en",
    }
    expect(bundlePath("/matches/m/session-pack", pack)).toBe(
      "matches/m/session-pack/1.half.s.coach.en.json"
    )
  })
})

describe("fallback source", () => {
  it("starts offline when the API doesn't answer its health check", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("fetch failed"))
    )
    const api = new ApiSource("http://api")
    const source = new FallbackSource(
      api,
      new BundleSource("/bundle/"),
      await api.health()
    )
    expect(source.getState()).toMatchObject({
      mode: "offline",
      hasApi: true,
      lost: false,
    })
  })

  it("answers from the bundle and says so when the API stops answering mid-session", async () => {
    const fetch = vi.fn(async (url: string) => {
      if (url.startsWith("http://api/health")) return json(HEALTH)
      if (url.startsWith("http://api")) throw new TypeError("fetch failed")
      return json([{ id: "from-bundle" }])
    })
    vi.stubGlobal("fetch", fetch)
    const api = new ApiSource("http://api")
    const source = new FallbackSource(
      api,
      new BundleSource("/bundle/"),
      await api.health()
    )
    expect(source.getState().mode).toBe("live")
    const changes = vi.fn()
    source.subscribe(changes)
    expect(await source.matches()).toEqual([{ id: "from-bundle" }])
    expect(source.getState()).toMatchObject({ mode: "offline", lost: true })
    expect(changes).toHaveBeenCalledOnce()
    expect(fetch).toHaveBeenLastCalledWith("/bundle/matches.json", undefined)
  })

  it("treats missing files as not found rather than falling back", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ detail: "not found" }, 404))
    )
    const source = new FallbackSource(null, new BundleSource("/bundle/"), null)
    await expect(source.possession("nope")).rejects.toThrow("not found")
    expect(await source.positions("nope")).toBeNull()
  })

  it("goes back live only when the API answers", async () => {
    let up = false
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => (up ? json(HEALTH) : json({}, 503)))
    )
    const source = new FallbackSource(
      new ApiSource("http://api"),
      new BundleSource("/bundle/"),
      null
    )
    expect(await source.goLive()).toBe(false)
    up = true
    expect(await source.goLive()).toBe(true)
    expect(source.getState()).toMatchObject({ mode: "live", health: HEALTH })
  })
})
