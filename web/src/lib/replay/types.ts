import type {
  Clock,
  Control,
  ErrorMessage,
  MatchEnd,
  NarrativeReady,
  PositionsMessage,
  PossessionFlagged,
} from "@/contracts"

/** A server message with its discriminant required (the generated types leave defaults optional). */
export type StreamMessage =
  | (Clock & { type: "clock" })
  | (PositionsMessage & { type: "positions" })
  | (PossessionFlagged & { type: "possession_flagged" })
  | (NarrativeReady & { type: "narrative" })
  | (MatchEnd & { type: "match_end" })
  | (ErrorMessage & { type: "error" })

export type ReplayParams = {
  style: string
  audience: "coach" | "player" | "fan"
  language: string
  speed: number
  fromMs: number
}

/** One replay of one match, from the API's WebSocket or played in the browser from the bundle. */
export interface ReplayStream {
  onMessage(listener: (message: StreamMessage) => void): () => void
  /** Called when the stream ends without close() being called: the API went away. */
  onLost(listener: () => void): () => void
  send(control: Control): void
  close(): void
}

export class Listeners<T extends unknown[]> {
  private listeners = new Set<(...args: T) => void>()

  add(listener: (...args: T) => void): () => void {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }

  emit(...args: T): void {
    for (const listener of this.listeners) listener(...args)
  }
}
