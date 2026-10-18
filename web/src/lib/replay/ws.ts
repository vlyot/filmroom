import type { Control } from "@/contracts"
import {
  Listeners,
  type ReplayStream,
  type StreamMessage,
} from "@/lib/replay/types"

/** The API's live replay over a WebSocket. */
export class WsReplay implements ReplayStream {
  private socket: WebSocket
  private messages = new Listeners<[StreamMessage]>()
  private lost = new Listeners<[]>()
  private queue: string[] = []
  private closed = false

  constructor(url: string) {
    this.socket = new WebSocket(url)
    this.socket.onopen = () => {
      for (const text of this.queue.splice(0)) this.socket.send(text)
    }
    this.socket.onmessage = (event) =>
      this.messages.emit(JSON.parse(event.data as string) as StreamMessage)
    this.socket.onclose = () => {
      if (!this.closed) this.lost.emit()
    }
  }

  onMessage(listener: (message: StreamMessage) => void) {
    return this.messages.add(listener)
  }

  onLost(listener: () => void) {
    return this.lost.add(listener)
  }

  send(control: Control) {
    const text = JSON.stringify({ ...control, type: "control" })
    if (this.socket.readyState === WebSocket.OPEN) this.socket.send(text)
    else this.queue.push(text)
  }

  close() {
    this.closed = true
    this.socket.close()
  }
}
