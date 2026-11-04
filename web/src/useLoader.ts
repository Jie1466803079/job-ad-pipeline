import { useCallback, useEffect, useState } from 'react'
import { messageOf } from './api.ts'

export interface Loaded<T> {
  data: T | undefined
  error: string | undefined
  reload: () => void
  replace: (data: T) => void
}

/**
 * Runs load() when key changes or reload() is called. An answer that arrives after the key
 * has changed is ignored, so a slow response never shows under the wrong tab or ad.
 */
export function useLoader<T>(key: string, load: () => Promise<T>): Loaded<T> {
  const [state, setState] = useState<{ key: string; data?: T; error?: string }>({ key })
  const [version, setVersion] = useState(0)

  useEffect(() => {
    let current = true
    load().then(
      (data) => {
        if (current) setState({ key, data })
      },
      (reason: unknown) => {
        if (current) setState({ key, error: messageOf(reason) })
      },
    )
    return () => {
      current = false
    }
    // load is a new function on every render; key and version decide when to run it again.
  }, [key, version])

  const reload = useCallback(() => setVersion((v) => v + 1), [])
  const replace = useCallback((data: T) => setState({ key, data }), [key])
  const fresh = state.key === key
  return { data: fresh ? state.data : undefined, error: fresh ? state.error : undefined, reload, replace }
}
