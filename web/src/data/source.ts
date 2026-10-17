/**
 * Where the data comes from. Today: static files under public/sample/<match>/.
 * When the FastAPI backend exists, swap `httpReader` (or the URLs) here; nothing else changes.
 */
import { DataError } from './validate'

/** Reads a text resource, given its path relative to the sample root ("<match>/<file>"). */
export type ReadText = (path: string) => Promise<string>

export function sampleUrl(path: string): string {
  return `${import.meta.env.BASE_URL}sample/${path}`
}

export const httpReader: ReadText = async (path) => {
  let res: Response
  try {
    res = await fetch(sampleUrl(path))
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
