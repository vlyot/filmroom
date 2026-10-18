import { useEffect, useEffectEvent, useState } from "react"

export type Resource<T> =
  | { status: "loading" }
  | { status: "error"; error: Error }
  | { status: "ready"; data: T }

const LOADING = { status: "loading" } as const

/** One async load, keyed: a new key starts over (and drops the old key's late result); null waits. */
export function useResource<T>(
  key: string | null,
  load: () => Promise<T>
): Resource<T> {
  const [state, setState] = useState<{
    key: string | null
    result: Resource<T>
  }>({
    key: null,
    result: LOADING,
  })
  const run = useEffectEvent(load)

  useEffect(() => {
    if (key === null) return
    let current = true
    run().then(
      (data) => current && setState({ key, result: { status: "ready", data } }),
      (error: unknown) =>
        current &&
        setState({
          key,
          result: {
            status: "error",
            error: error instanceof Error ? error : new Error(String(error)),
          },
        })
    )
    return () => {
      current = false
    }
  }, [key])

  return state.key === key ? state.result : LOADING
}
