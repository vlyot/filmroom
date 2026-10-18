import type { Narrative, PositionsChunk, PossessionSummary } from "@/contracts"
import { chunkEndMs, frameAt, type Frame } from "@/lib/positions"
import { Listeners, type StreamMessage } from "@/lib/replay/types"

export type FlagEntry = { summary: PossessionSummary; narrative: Narrative }

export type ReplaySnapshot = {
  tMs: number
  speed: number
  playing: boolean
  ended: boolean
  /** Every flag received, in the order the possessions ended. */
  flags: FlagEntry[]
  /** Narratives pushed once generated, by narrativeKey. */
  pushed: Record<string, Narrative>
}

const KEEP_TRACK_MS = 5000

export function narrativeKey(
  n: Pick<Narrative, "possession_id" | "style_id" | "audience" | "language">
) {
  return `${n.possession_id}|${n.style_id}|${n.audience}|${n.language}`
}

/** What one replay stream has said so far, for React (subscribe / getSnapshot) and for the pitch, which reads
 * the interpolated clock and positions every animation frame. */
export class ReplayStore {
  private snapshot: ReplaySnapshot = {
    tMs: 0,
    speed: 1,
    playing: false,
    ended: false,
    flags: [],
    pushed: {},
  }
  private clockAt = 0
  private tracks = new Map<string, PositionsChunk>()
  private changes = new Listeners<[]>()
  private arrivals = new Listeners<[FlagEntry]>()
  private durationMs: number

  constructor(durationMs: number) {
    this.durationMs = durationMs
  }

  subscribe = (listener: () => void) => this.changes.add(listener)
  getSnapshot = () => this.snapshot
  onNewFlag = (listener: (entry: FlagEntry) => void) =>
    this.arrivals.add(listener)

  private update(next: Partial<ReplaySnapshot>) {
    this.snapshot = { ...this.snapshot, ...next }
    this.changes.emit()
  }

  receive(message: StreamMessage, now: number) {
    switch (message.type) {
      case "clock":
        this.clockAt = now
        this.update({
          tMs: message.t_ms,
          speed: message.speed,
          playing: message.playing,
          ended: message.playing ? false : this.snapshot.ended,
        })
        this.pruneTracks(message.t_ms)
        break
      case "positions":
        this.addTrack(message.chunk)
        break
      case "possession_flagged": {
        const entry = { summary: message.summary, narrative: message.narrative }
        const known = this.snapshot.flags.some(
          (f) => f.summary.id === entry.summary.id
        )
        const flags = [
          ...this.snapshot.flags.filter(
            (f) => f.summary.id !== entry.summary.id
          ),
          entry,
        ]
        this.update({
          flags: flags.sort((a, b) => a.summary.end_ms - b.summary.end_ms),
        })
        if (!known) this.arrivals.emit(entry)
        break
      }
      case "narrative":
        this.update({
          pushed: {
            ...this.snapshot.pushed,
            [narrativeKey(message.narrative)]: message.narrative,
          },
        })
        break
      case "match_end":
        this.update({ ended: true, playing: false })
        break
      case "error":
        console.warn("replay:", message.message)
        break
    }
  }

  /** The clock now, run on from the last tick at the replay's speed. */
  timeAt(now: number): number {
    const { tMs, speed, playing } = this.snapshot
    return playing
      ? Math.min(this.durationMs, tMs + (now - this.clockAt) * speed)
      : tMs
  }

  frameAt(tMs: number): Frame | null {
    for (const chunk of this.tracks.values()) {
      const frame = frameAt(chunk, tMs)
      if (frame) return frame
    }
    return null
  }

  private addTrack(slice: PositionsChunk) {
    const track = this.tracks.get(slice.possession_id)
    const next = track ? Math.round(chunkEndMs(track) + 1000 / track.hz) : null
    if (track && slice.t0_ms === next) {
      this.tracks.set(slice.possession_id, {
        ...track,
        xy: [...track.xy, ...slice.xy],
      })
    } else {
      this.tracks.set(slice.possession_id, slice) // the first slice, or the first after a seek
    }
  }

  private pruneTracks(tMs: number) {
    for (const [id, track] of this.tracks) {
      if (
        chunkEndMs(track) < tMs - KEEP_TRACK_MS ||
        track.t0_ms > tMs + KEEP_TRACK_MS
      )
        this.tracks.delete(id)
    }
  }
}
