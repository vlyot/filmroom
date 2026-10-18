import { describe, expect, it } from "vitest"

import type { Narrative, PositionsChunk, PossessionSummary } from "@/contracts"
import { ReplayCore, sliceChunk } from "@/lib/replay/core"
import type { StreamMessage } from "@/lib/replay/types"

const summary = (
  id: string,
  start: number,
  end: number,
  flagged: boolean
): PossessionSummary => ({
  id,
  match_id: "m",
  team: 0,
  start_ms: start,
  end_ms: end,
  outcome: "lost_pass",
  ended_zone: "mid",
  flagged,
  severity: 0.5,
  turning_point_idx: flagged ? 0 : null,
  provenance: "engine",
})

const POSSESSIONS = [
  summary("a", 0, 2290, true),
  summary("b", 2600, 3990, false),
  summary("c", 4500, 5790, true),
]
const track = (id: string, t0: number, rows: number): PositionsChunk => ({
  possession_id: id,
  t0_ms: t0,
  hz: 10,
  pids: [128],
  xy: Array.from({ length: rows }, (_, i) => [i, 0]),
})

function core(speed = 1, fromMs = 0, tracks = true) {
  return new ReplayCore(
    {
      possessions: POSSESSIONS,
      durationMs: 6090,
      positions: async (id) =>
        tracks && id === "a" ? track("a", 0, 23) : null,
      narrate: async (p) => ({ possession_id: p.id }) as Narrative,
    },
    speed,
    fromMs
  )
}

const flagged = (messages: StreamMessage[]) =>
  messages.flatMap((m) =>
    m.type === "possession_flagged" ? [m.summary.id] : []
  )

describe("replay core", () => {
  it("moves the clock by wall time times speed, and holds it while paused", async () => {
    const replay = core(2)
    await replay.advance(0)
    await replay.advance(100)
    expect(replay.tMs).toBe(200)
    replay.control({ action: "pause" })
    const paused = [
      ...(await replay.advance(500)),
      ...(await replay.advance(500)),
    ]
    expect(replay.tMs).toBe(200)
    expect(paused.filter((m) => m.type === "clock")).toEqual([
      { type: "clock", t_ms: 200, speed: 2, playing: false },
    ])
  })

  it("sends each flagged possession once, after its end only", async () => {
    const replay = core(10)
    expect(flagged(await replay.advance(200))).toEqual([])
    expect(flagged(await replay.advance(30))).toEqual(["a"])
    expect(flagged(await replay.advance(300))).toEqual([]) // b ended but isn't flagged
  })

  it("sends skipped flags on a forward seek and again after seeking back", async () => {
    const replay = core()
    replay.control({ action: "seek", value: 6000 })
    expect(flagged(await replay.advance(0))).toEqual(["a", "c"])
    replay.control({ action: "seek", value: 3000 })
    replay.control({ action: "seek", value: 5800 })
    expect(flagged(await replay.advance(0))).toEqual(["c"])
  })

  it("slices positions a second ahead of the clock and skips possessions without a track", async () => {
    const replay = core()
    const first = (await replay.advance(0)).flatMap((m) =>
      m.type === "positions" ? [m.chunk] : []
    )
    expect(first.map((c) => [c.t0_ms, c.xy.length])).toEqual([[0, 10]])
    const next = (await replay.advance(100)).flatMap((m) =>
      m.type === "positions" ? [m.chunk] : []
    )
    expect(next.map((c) => [c.t0_ms, c.xy.length])).toEqual([[1000, 1]])
    const none = await core(1, 0, false).advance(0)
    expect(none.some((m) => m.type === "positions")).toBe(false)
  })

  it("ends at the match duration, and play starts it over", async () => {
    const replay = core(10)
    const messages = await replay.advance(1000)
    expect(messages.at(-1)).toEqual({ type: "match_end" })
    expect(replay.playing).toBe(false)
    expect(await replay.advance(100)).toEqual([])
    replay.control({ action: "play" })
    expect([replay.tMs, replay.playing]).toEqual([0, true])
  })

  it("clamps speed and rejects controls without a value", () => {
    const replay = core(50)
    expect(replay.speed).toBe(10)
    replay.control({ action: "speed", value: 0.2 })
    expect(replay.speed).toBe(1)
    expect(replay.control({ action: "seek" })).toEqual([
      { type: "error", message: "seek needs a value" },
    ])
  })

  it("cuts chunks to a time window", () => {
    const part = sliceChunk(track("a", 1000, 20), 1250, 1600)!
    expect([part.t0_ms, part.xy.map((r) => r[0])]).toEqual([1300, [3, 4, 5]])
    expect(sliceChunk(track("a", 1000, 20), 4000, 5000)).toBeNull()
  })
})
