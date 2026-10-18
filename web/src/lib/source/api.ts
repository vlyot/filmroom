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
import type { ReplayParams } from "@/lib/replay/types"
import { WsReplay } from "@/lib/replay/ws"
import { Memo, query, requestJson } from "@/lib/source/http"
import {
  NotFound,
  type DataSource,
  type NarrativeQuery,
  type PackQuery,
} from "@/lib/source/types"

const HEALTH_TIMEOUT_MS = 3000

/** The FilmRoom API: REST for data, a WebSocket for the live replay. */
export class ApiSource implements DataSource {
  private memo = new Memo()
  private base: string

  constructor(base: string) {
    this.base = base.replace(/\/$/, "")
  }

  private get<T>(path: string): Promise<T> {
    return this.memo.get(path, () => requestJson<T>(this.base + path))
  }

  /** null when the API doesn't answer within a few seconds. */
  async health(): Promise<Health | null> {
    try {
      return await requestJson<Health>(`${this.base}/health`, {
        signal: AbortSignal.timeout(HEALTH_TIMEOUT_MS),
      })
    } catch {
      return null
    }
  }

  matches = () => this.get<MatchSummary[]>("/matches")
  match = (id: string) => this.get<Match>(`/matches/${id}`)
  possessions = (matchId: string) =>
    this.get<PossessionSummary[]>(`/matches/${matchId}/possessions`)
  possession = (id: string) => this.get<Possession>(`/possessions/${id}`)
  styles = () => this.get<StyleConfig[]>("/styles")
  lens = () => this.get<StyleLens>("/styles/lens")

  async positions(id: string): Promise<PositionsChunk | null> {
    try {
      return await this.get<PositionsChunk>(`/possessions/${id}/positions`)
    } catch (error) {
      if (error instanceof NotFound) return null
      throw error
    }
  }

  // Not memoised: a pending narrative is polled until the verified one arrives.
  narrative(possessionId: string, q: NarrativeQuery): Promise<Narrative> {
    return requestJson(
      `${this.base}/possessions/${possessionId}/narrative?${query(q)}`
    )
  }

  sessionPack(matchId: string, q: PackQuery): Promise<SessionPack> {
    return this.get(`/matches/${matchId}/session-pack?${query(q)}`)
  }

  overlay(matchId: string, style: string): Promise<OverlayEvent[]> {
    return this.get(`/matches/${matchId}/overlay?${query({ style })}`)
  }

  overlayUrl(matchId: string, style: string): string {
    return `${this.base}/matches/${matchId}/overlay?${query({ style })}`
  }

  analyst(request: AnalystRequest): Promise<AnalystReply> {
    return requestJson(`${this.base}/analyst`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(request),
    })
  }

  replay(matchId: string, p: ReplayParams) {
    const params = query({
      style: p.style,
      audience: p.audience,
      language: p.language,
      speed: p.speed,
      from_ms: Math.round(p.fromMs),
    })
    const url = new URL(
      `${this.base}/matches/${matchId}/replay?${params}`,
      window.location.href
    )
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:"
    return new WsReplay(url.toString())
  }
}
