import type { Control } from "@/contracts"
import { ReplayCore, type ReplayDeps } from "@/lib/replay/core"
import {
  Listeners,
  type ReplayStream,
  type StreamMessage,
} from "@/lib/replay/types"

const TICK_MS = 100

/** The replay played in the browser for offline mode: the server's clock on a timer. */
export class LocalReplay implements ReplayStream {
  private messages = new Listeners<[StreamMessage]>()
  private core: Promise<ReplayCore>
  private timer: ReturnType<typeof setInterval> | undefined
  private busy = false
  private closed = false
  private last = 0

  constructor(deps: Promise<ReplayDeps>, speed: number, fromMs: number) {
    this.core = deps.then((d) => new ReplayCore(d, speed, fromMs))
    void this.core.then((core) => {
      if (this.closed) return
      this.last = performance.now()
      void this.tick(core)
      this.timer = setInterval(() => void this.tick(core), TICK_MS)
    })
  }

  /** One step of the clock. While a slow fetch holds a step, later ticks are skipped rather than stacked;
   * the time they cover goes into the next step, so the clock keeps its speed. */
  private async tick(core: ReplayCore) {
    if (this.busy) return
    this.busy = true
    const now = performance.now()
    const wall = now - this.last
    this.last = now
    try {
      for (const message of await core.advance(wall))
        this.messages.emit(message)
    } finally {
      this.busy = false
    }
  }

  onMessage(listener: (message: StreamMessage) => void) {
    return this.messages.add(listener)
  }

  onLost() {
    return () => {}
  }

  send(control: Control) {
    void this.core.then((core) => {
      for (const message of core.control(control)) this.messages.emit(message)
    })
  }

  close() {
    this.closed = true
    clearInterval(this.timer)
  }
}
