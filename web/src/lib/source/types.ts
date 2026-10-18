import type {
  AnalystReply,
  AnalystRequest,
  Health,
  Match,
  MatchSummary,
  Narrative,
  OverlayEvent,
  PositionsChunk,
  Possession,
  PossessionSummary,
  SessionPack,
  StyleConfig,
  StyleLens,
} from "@/contracts"
import type { ReplayParams, ReplayStream } from "@/lib/replay/types"

export type Mode = "live" | "offline"
export type Audience = Narrative["audience"]

export type NarrativeQuery = {
  style: string
  audience: Audience
  language: string
}
export type PackQuery = {
  team: 0 | 1
  period: "half" | "full"
  style: string
  audience: Audience
  language: string
}

/** Where the app's data comes from: the API (live) or the static bundle (offline). Both answer with the same
 * contract types; the bundle holds the API's responses as files. */
export interface DataSource {
  health(): Promise<Health | null>
  matches(): Promise<MatchSummary[]>
  match(id: string): Promise<Match>
  possessions(matchId: string): Promise<PossessionSummary[]>
  possession(id: string): Promise<Possession>
  /** null when positions aren't published (the public bundle). */
  positions(id: string): Promise<PositionsChunk | null>
  styles(): Promise<StyleConfig[]>
  lens(): Promise<StyleLens>
  narrative(possessionId: string, query: NarrativeQuery): Promise<Narrative>
  sessionPack(matchId: string, query: PackQuery): Promise<SessionPack>
  overlay(matchId: string, style: string): Promise<OverlayEvent[]>
  analyst(request: AnalystRequest): Promise<AnalystReply>
  replay(matchId: string, params: ReplayParams): ReplayStream
}

/** The source didn't answer (network error or a server error): time to fall back. */
export class Unavailable extends Error {}

/** The source answered that this doesn't exist. */
export class NotFound extends Error {}
