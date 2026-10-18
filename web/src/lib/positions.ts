import type { PositionsChunk } from "@/contracts"

export type Frame = { pids: number[]; xy: (number | null)[] }

/** Positions at time t, interpolated between the chunk's samples; null outside the chunk. */
export function frameAt(chunk: PositionsChunk, tMs: number): Frame | null {
  const index = ((tMs - chunk.t0_ms) * chunk.hz) / 1000
  if (index < 0 || index > chunk.xy.length - 1) return null
  const lo = Math.floor(index)
  const hi = Math.min(chunk.xy.length - 1, lo + 1)
  const f = index - lo
  const a = chunk.xy[lo]
  const b = chunk.xy[hi]
  return {
    pids: chunk.pids,
    xy: a.map((v, k) =>
      v === null || b[k] === null ? v : v + (b[k]! - v) * f
    ),
  }
}

export function chunkEndMs(chunk: PositionsChunk): number {
  return chunk.t0_ms + ((chunk.xy.length - 1) * 1000) / chunk.hz
}

/** Where one entity is in a frame, or null when its sample is missing. */
export function positionOf(frame: Frame, pid: number): [number, number] | null {
  const k = frame.pids.indexOf(pid)
  if (k < 0) return null
  const x = frame.xy[2 * k]
  const y = frame.xy[2 * k + 1]
  return x === null || y === null ? null : [x, y]
}
