// The replay clock as filmroom/api/replay.py runs it on the server: the same messages at the same moments,
// so a replay played from the static bundle behaves like the live one.

import type {
  Control,
  Narrative,
  PositionsChunk,
  PossessionSummary,
} from "@/contracts"
import type { StreamMessage } from "@/lib/replay/types"

export const SLICE_MS = 1000
export const MIN_SPEED = 1
export const MAX_SPEED = 10

const clampSpeed = (value: number) =>
  Math.min(MAX_SPEED, Math.max(MIN_SPEED, value))

/** The samples timed in [t0, t1), or null when there are none. */
export function sliceChunk(
  chunk: PositionsChunk,
  t0: number,
  t1: number
): PositionsChunk | null {
  const step = 1000 / chunk.hz
  const first = Math.max(0, Math.ceil((t0 - chunk.t0_ms) / step))
  const stop = Math.min(chunk.xy.length, Math.ceil((t1 - chunk.t0_ms) / step))
  if (first >= stop) return null
  return {
    ...chunk,
    t0_ms: Math.round(chunk.t0_ms + first * step),
    xy: chunk.xy.slice(first, stop),
  }
}

export type ReplayDeps = {
  possessions: PossessionSummary[]
  durationMs: number
  positions: (possessionId: string) => Promise<PositionsChunk | null>
  narrate: (possession: PossessionSummary) => Promise<Narrative>
}

export class ReplayCore {
  speed: number
  playing = true
  tMs = 0
  private possessions: PossessionSummary[]
  private deps: ReplayDeps
  private sent = new Set<string>()
  private chunks = new Map<string, Promise<PositionsChunk | null>>()
  private slicedTo = 0
  private ended = false
  private dirty = true

  constructor(deps: ReplayDeps, speed = 1, fromMs = 0) {
    this.deps = deps
    this.possessions = [...deps.possessions].sort(
      (a, b) => a.start_ms - b.start_ms
    )
    this.speed = clampSpeed(speed)
    this.seek(fromMs)
  }

  private byId(id: string) {
    return this.possessions.find((p) => p.id === id)!
  }

  private seek(tMs: number) {
    this.tMs = Math.min(this.deps.durationMs, Math.max(0, tMs))
    this.slicedTo = this.tMs
    this.ended = this.tMs >= this.deps.durationMs
    this.sent = new Set(
      [...this.sent].filter((id) => this.byId(id).end_ms <= this.tMs)
    )
  }

  clock(): StreamMessage {
    return {
      type: "clock",
      t_ms: Math.round(this.tMs),
      speed: this.speed,
      playing: this.playing,
    }
  }

  async advance(wallMs: number): Promise<StreamMessage[]> {
    if (this.playing)
      this.tMs = Math.min(this.deps.durationMs, this.tMs + wallMs * this.speed)
    const reachedEnd = this.tMs >= this.deps.durationMs && !this.ended
    if (reachedEnd) [this.ended, this.playing] = [true, false]
    const messages: StreamMessage[] = []
    if (this.playing || this.dirty || reachedEnd) {
      messages.push(this.clock())
      this.dirty = false
    }
    messages.push(...(await this.positionSlices()), ...(await this.flags()))
    if (reachedEnd) messages.push({ type: "match_end" })
    return messages
  }

  control(control: Control): StreamMessage[] {
    const needsValue = control.action === "speed" || control.action === "seek"
    if (needsValue && (control.value === null || control.value === undefined)) {
      return [{ type: "error", message: `${control.action} needs a value` }]
    }
    if (control.action === "play") {
      if (this.ended) this.seek(0)
      this.playing = true
    } else if (control.action === "pause") {
      this.playing = false
    } else if (control.action === "speed") {
      this.speed = clampSpeed(control.value!)
    } else {
      this.seek(control.value!)
    }
    this.dirty = true
    return []
  }

  private async positionSlices(): Promise<StreamMessage[]> {
    const messages: StreamMessage[] = []
    const horizon = Math.min(this.deps.durationMs, this.tMs + SLICE_MS)
    while (this.slicedTo < horizon) {
      const start = this.slicedTo
      const stop = Math.min(horizon, start + SLICE_MS)
      for (const possession of this.possessions) {
        if (possession.start_ms < stop && possession.end_ms >= start) {
          const chunk = await this.chunk(possession.id)
          const part = chunk && sliceChunk(chunk, start, stop)
          if (part) messages.push({ type: "positions", chunk: part })
        }
      }
      this.slicedTo = stop
      for (const id of this.chunks.keys()) {
        if (this.byId(id).end_ms < stop) this.chunks.delete(id)
      }
    }
    return messages
  }

  private chunk(id: string): Promise<PositionsChunk | null> {
    if (!this.chunks.has(id)) this.chunks.set(id, this.deps.positions(id))
    return this.chunks.get(id)!
  }

  private async flags(): Promise<StreamMessage[]> {
    const due = this.possessions.filter(
      (p) => p.flagged && p.end_ms <= this.tMs && !this.sent.has(p.id)
    )
    for (const p of due) this.sent.add(p.id)
    const narratives = await Promise.all(due.map((p) => this.deps.narrate(p)))
    return due.map((summary, i) => ({
      type: "possession_flagged",
      summary,
      narrative: narratives[i],
    }))
  }
}
