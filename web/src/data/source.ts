/**
 * Where the demo data comes from.
 *   - Static demo build (no VITE_API_URL): files under public/sample/<match>/ (copied from
 *     ../samples by scripts/copy-samples.mjs).
 *   - Connected (VITE_API_URL set, incl. "/" for same-origin): the backend's demo endpoints,
 *     GET /api/demo/files/<name> (the same files, served by FastAPI) and GET /api/demo/alerts
 *     (the demo alerts with this visitor's own approve / reject; see loadAlerts).
 */
import { apiConfigured, apiUrl } from './api'
import { DataError } from './validate'

/** Reads a text resource, given its path relative to the sample root ("<match>/<file>"). */
export type ReadText = (path: string) => Promise<string>

/** True when the demo is read from the backend instead of the bundled files. */
export function demoFromApi(): boolean {
  return apiConfigured()
}

export function sampleUrl(path: string): string {
  if (demoFromApi()) {
    // the backend serves the demo files by base name (whitelist: config.yaml api.demo.files)
    const name = path.split('/').at(-1) ?? path
    return apiUrl(`/api/demo/files/${encodeURIComponent(name)}`)
  }
  return `${import.meta.env.BASE_URL}sample/${path}`
}

export const httpReader: ReadText = async (path) => {
  let res: Response
  try {
    res = await fetch(sampleUrl(path), demoFromApi() ? { credentials: 'include' } : undefined)
  } catch {
    throw new DataError(`could not reach ${path} (network error)`)
  }
  if (!res.ok) throw new DataError(`could not load ${path} (HTTP ${res.status})`)
  return res.text()
}

export async function readJson(read: ReadText, path: string): Promise<unknown> {
  const text = await read(path)
  try {
    return JSON.parse(text) as unknown
  } catch {
    throw new DataError(`${path} is not valid JSON`)
  }
}
