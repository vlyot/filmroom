import type {
  AnalystReply,
  BundleManifest,
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
import { LocalReplay } from "@/lib/replay/local"
import type { ReplayParams } from "@/lib/replay/types"
import { Memo, requestJson } from "@/lib/source/http"
import {
  NotFound,
  type DataSource,
  type NarrativeQuery,
  type PackQuery,
} from "@/lib/source/types"

/** The bundle file holding a route's response, as filmroom.api.bundle.route_to_path names it: query values
 * joined in order, e.g. narrative/{style}.{audience}.{language}.json. */
export function bundlePath(
  route: string,
  params?: Record<string, string | number>
): string {
  const path = route.replace(/^\/+|\/+$/g, "")
  return params
    ? `${path}/${Object.values(params).join(".")}.json`
    : `${path}.json`
}

/** The static bundle: the API's GET responses exported as files (scripts/export_bundle.py). */
export class BundleSource implements DataSource {
  private memo = new Memo()
  private base: string

  constructor(base: string) {
    this.base = base.endsWith("/") ? base : `${base}/`
  }

  private get<T>(
    route: string,
    params?: Record<string, string | number>
  ): Promise<T> {
    const path = bundlePath(route, params)
    return this.memo.get(path, () => requestJson<T>(this.base + path))
  }

  manifest = () =>
    this.memo.get("manifest", () =>
      requestJson<BundleManifest>(`${this.base}manifest.json`)
    )

  health = async () => null
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

  narrative(possessionId: string, q: NarrativeQuery): Promise<Narrative> {
    return this.get(`/possessions/${possessionId}/narrative`, {
      style: q.style,
      audience: q.audience,
      language: q.language,
    })
  }

  sessionPack(matchId: string, q: PackQuery): Promise<SessionPack> {
    return this.get(`/matches/${matchId}/session-pack`, {
      team: q.team,
      period: q.period,
      style: q.style,
      audience: q.audience,
      language: q.language,
    })
  }

  overlay(matchId: string, style: string): Promise<OverlayEvent[]> {
    return this.get(`/matches/${matchId}/overlay`, { style })
  }

  async analyst(): Promise<AnalystReply> {
    return { text: "", possession_ids: [], status: "offline", model: null }
  }

  replay(matchId: string, p: ReplayParams) {
    const deps = Promise.all([
      this.match(matchId),
      this.possessions(matchId),
    ]).then(([match, possessions]) => ({
      possessions,
      durationMs: match.duration_ms,
      positions: (id: string) => this.positions(id),
      narrate: (s: PossessionSummary) =>
        this.narrative(s.id, {
          style: p.style,
          audience: p.audience,
          language: p.language,
        }),
    }))
    return new LocalReplay(deps, p.speed, p.fromMs)
  }
}
