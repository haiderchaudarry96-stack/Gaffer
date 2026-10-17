import { useEffect, useState } from 'react'

export type Resource<T> =
  | { status: 'loading' }
  | { status: 'error'; error: string }
  | { status: 'ready'; data: T }

/** Runs a data-layer loader once (per key) and tracks loading / error / ready. */
export function useResource<T>(load: () => Promise<T>, key: string): Resource<T> {
  const [state, setState] = useState<{ key: string; res: Resource<T> }>({ key, res: { status: 'loading' } })

  useEffect(() => {
    let alive = true
    load().then(
      (data) => alive && setState({ key, res: { status: 'ready', data } }),
      (err: unknown) =>
        alive && setState({ key, res: { status: 'error', error: err instanceof Error ? err.message : String(err) } }),
    )
    return () => {
      alive = false
    }
    // the loader is identified by `key`
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  return state.key === key ? state.res : { status: 'loading' }
}
