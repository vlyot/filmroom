import { afterEach, describe, expect, it, vi } from "vitest"

import { ApiSource } from "@/lib/source/api"
import { BundleSource, bundlePath } from "@/lib/source/bundle"
import { FallbackSource, REPROBE_MS } from "@/lib/source/fallback"

const HEALTH = {
  status: "ok",
  contract_version: "0.6.0",
  source: "engine",
  llm: true,
} as const
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  })

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

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

  it("reports the API's metrics live, nothing offline, and falls back when they fail", async () => {
    let up = true
    const fetch = vi.fn(async (url: string) => {
      if (!up) throw new TypeError("fetch failed")
      return json(url.endsWith("/metrics") ? { uptime_s: 5 } : HEALTH)
    })
    vi.stubGlobal("fetch", fetch)
    const api = new ApiSource("http://api")
    const source = new FallbackSource(
      api,
      new BundleSource("/bundle/"),
      await api.health()
    )
    expect(await source.metrics()).toEqual({ uptime_s: 5 })
    up = false
    expect(await source.metrics()).toBeNull()
    expect(source.getState()).toMatchObject({ mode: "offline", lost: true })
    const calls = fetch.mock.calls.length
    expect(await source.metrics()).toBeNull()
    expect(fetch.mock.calls.length).toBe(calls)
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

describe("re-probing while offline", () => {
  /** An API that is down until `up` is set, behind a source that started offline. */
  function setup() {
    const api = { up: false }
    const fetch = vi.fn(async (url: string) => {
      if (url.startsWith("http://api") && !api.up)
        throw new TypeError("fetch failed")
      return json(url.startsWith("http://api") ? HEALTH : [])
    })
    vi.stubGlobal("fetch", fetch)
    vi.useFakeTimers()
    const source = new FallbackSource(
      new ApiSource("http://api"),
      new BundleSource("/bundle/"),
      null
    )
    const healthCalls = () =>
      fetch.mock.calls.filter(([url]) => url.startsWith("http://api/health"))
        .length
    return { api, source, healthCalls }
  }

  it("goes live once the API that was down at load answers", async () => {
    const { api, source } = setup()
    const stop = source.watch()
    await vi.advanceTimersByTimeAsync(REPROBE_MS)
    expect(source.getState().mode).toBe("offline")
    api.up = true
    await vi.advanceTimersByTimeAsync(REPROBE_MS)
    expect(source.getState()).toMatchObject({
      mode: "live",
      health: HEALTH,
      restored: true,
    })
    stop()
  })

  it("comes back after losing the API mid-session", async () => {
    const { api, source } = setup()
    api.up = true
    expect(await source.goLive()).toBe(true)
    api.up = false
    await source.matches()
    expect(source.getState()).toMatchObject({ mode: "offline", lost: true })
    const stop = source.watch()
    api.up = true
    await vi.advanceTimersByTimeAsync(REPROBE_MS)
    expect(source.getState()).toMatchObject({ mode: "live", lost: false })
    stop()
  })

  it("never probes after offline was chosen by hand", async () => {
    const { api, source, healthCalls } = setup()
    api.up = true
    await source.goLive()
    source.goOffline("manual")
    const before = healthCalls()
    const stop = source.watch()
    await vi.advanceTimersByTimeAsync(REPROBE_MS * 3)
    expect(healthCalls()).toBe(before)
    expect(source.getState()).toMatchObject({ mode: "offline", manual: true })
    stop()
  })

  it("stops probing once live", async () => {
    const { api, source, healthCalls } = setup()
    api.up = true
    const stop = source.watch()
    await vi.advanceTimersByTimeAsync(REPROBE_MS)
    const after = healthCalls()
    await vi.advanceTimersByTimeAsync(REPROBE_MS * 3)
    expect(healthCalls()).toBe(after)
    stop()
  })

  it("skips probes while the tab is hidden", async () => {
    const { api, source, healthCalls } = setup()
    vi.stubGlobal("document", { hidden: true })
    api.up = true
    const stop = source.watch()
    await vi.advanceTimersByTimeAsync(REPROBE_MS * 2)
    expect(healthCalls()).toBe(0)
    expect(source.getState().mode).toBe("offline")
    stop()
  })
})
