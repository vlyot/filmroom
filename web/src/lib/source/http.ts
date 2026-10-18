import { NotFound, Unavailable } from "@/lib/source/types"

export async function requestJson<T>(
  url: string,
  init?: RequestInit
): Promise<T> {
  let response: Response
  try {
    response = await fetch(url, init)
  } catch (error) {
    throw new Unavailable(
      `${url}: ${error instanceof Error ? error.message : String(error)}`
    )
  }
  if (response.status >= 500)
    throw new Unavailable(`${url}: ${response.status}`)
  // Dev servers answer missing files with index.html, so a 200 alone doesn't mean the file exists.
  const isJson = response.headers.get("content-type")?.includes("json")
  if (!response.ok || !isJson) throw new NotFound(`${url}: not found`)
  return (await response.json()) as T
}

/** Remembers each GET's promise, dropping failures so they can be retried. */
export class Memo {
  private entries = new Map<string, Promise<unknown>>()

  get<T>(key: string, load: () => Promise<T>): Promise<T> {
    if (!this.entries.has(key)) {
      const promise = load()
      promise.catch(() => this.entries.delete(key))
      this.entries.set(key, promise)
    }
    return this.entries.get(key) as Promise<T>
  }
}

export function query(params: Record<string, string | number>): string {
  return new URLSearchParams(
    Object.entries(params).map(([k, v]) => [k, String(v)])
  ).toString()
}
