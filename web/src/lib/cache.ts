/** Module-level promise cache so moving between / and /app does not refetch the same file. */
const cache = new Map<string, Promise<unknown>>()

export function cached<T>(key: string, load: () => Promise<T>): () => Promise<T> {
  return () => {
    let p = cache.get(key) as Promise<T> | undefined
    if (!p) {
      p = load()
      cache.set(key, p)
      p.catch(() => cache.delete(key))
    }
    return p
  }
}
