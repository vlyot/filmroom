import type { AnalystRequest, Health } from "@/contracts"
import type { ReplayParams } from "@/lib/replay/types"
import { Listeners } from "@/lib/replay/types"
import { ApiSource } from "@/lib/source/api"
import { BundleSource } from "@/lib/source/bundle"
import {
  Unavailable,
  type DataSource,
  type Mode,
  type NarrativeQuery,
  type PackQuery,
} from "@/lib/source/types"

export type SourceState = {
  mode: Mode
  /** The API's health while live: `llm` says whether narratives are generated and the analyst answers. */
  health: Health | null
  /** Whether an API is configured at all (VITE_API_URL). */
  hasApi: boolean
  /** Offline because the API stopped answering, rather than by choice. */
  lost: boolean
}

/** The API while it answers, the static bundle otherwise. A request that fails to reach the API switches the
 * app to the bundle for good (until someone switches back) and is answered from the bundle. */
export class FallbackSource implements DataSource {
  readonly bundle: BundleSource
  private api: ApiSource | null
  private state: SourceState
  private changes = new Listeners<[]>()

  constructor(
    api: ApiSource | null,
    bundle: BundleSource,
    health: Health | null
  ) {
    this.api = api
    this.bundle = bundle
    this.state = {
      mode: api && health ? "live" : "offline",
      health,
      hasApi: api !== null,
      lost: false,
    }
  }

  subscribe = (listener: () => void) => this.changes.add(listener)
  getState = () => this.state

  private set(update: Partial<SourceState>) {
    this.state = { ...this.state, ...update }
    this.changes.emit()
  }

  private get active(): DataSource {
    return this.state.mode === "live" && this.api ? this.api : this.bundle
  }

  goOffline(lost = false) {
    if (this.state.mode === "offline") return
    this.set({ mode: "offline", health: null, lost })
  }

  /** Back to the API if it answers; false when it doesn't. */
  async goLive(): Promise<boolean> {
    const health = (await this.api?.health()) ?? null
    if (!health) return false
    this.set({ mode: "live", health, lost: false })
    return true
  }

  /** After a live stream dropped: falls back if the API no longer answers. */
  async check(): Promise<void> {
    if (this.state.mode === "live" && !(await this.api!.health()))
      this.goOffline(true)
  }

  private async call<T>(
    request: (source: DataSource) => Promise<T>
  ): Promise<T> {
    const source = this.active
    try {
      return await request(source)
    } catch (error) {
      if (!(error instanceof Unavailable) || source === this.bundle) throw error
      this.goOffline(true)
      return request(this.bundle)
    }
  }

  health = async () => this.state.health
  matches = () => this.call((s) => s.matches())
  match = (id: string) => this.call((s) => s.match(id))
  possessions = (matchId: string) => this.call((s) => s.possessions(matchId))
  possession = (id: string) => this.call((s) => s.possession(id))
  positions = (id: string) => this.call((s) => s.positions(id))
  styles = () => this.call((s) => s.styles())
  lens = () => this.call((s) => s.lens())
  narrative = (id: string, q: NarrativeQuery) =>
    this.call((s) => s.narrative(id, q))
  sessionPack = (matchId: string, q: PackQuery) =>
    this.call((s) => s.sessionPack(matchId, q))
  overlay = (matchId: string, style: string) =>
    this.call((s) => s.overlay(matchId, style))
  analyst = (request: AnalystRequest) => this.call((s) => s.analyst(request))
  replay = (matchId: string, params: ReplayParams) =>
    this.active.replay(matchId, params)

  /** The live overlay feed's URL, for broadcast systems to poll; null offline. */
  overlayUrl(matchId: string, style: string): string | null {
    return this.state.mode === "live" && this.api
      ? this.api.overlayUrl(matchId, style)
      : null
  }
}

/** Probes the API named by VITE_API_URL; the bundle serves everything when there is none or it is down. */
export async function connectSource(): Promise<FallbackSource> {
  const bundle = new BundleSource(`${import.meta.env.BASE_URL}bundle/`)
  const url = import.meta.env.VITE_API_URL as string | undefined
  const api = url ? new ApiSource(url) : null
  return new FallbackSource(api, bundle, api ? await api.health() : null)
}
