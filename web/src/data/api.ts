/**
 * Minimal client for the Gaffer FastAPI backend (contract in web/README.md, "Backend API").
 * The base URL comes from VITE_API_URL; when it is empty the site is a static demo and every
 * call throws ApiNotConfigured, so the UI can say so instead of pretending.
 */

export class ApiNotConfigured extends Error {
  constructor() {
    super('Analysis server not connected in this demo build')
    this.name = 'ApiNotConfigured'
  }
}

export class ApiError extends Error {
  readonly status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** The network functions the data layer uses; tests pass a fake. */
export interface Http {
  fetch: (url: string, init?: RequestInit) => Promise<Response>
  /** multipart upload with progress (0..1); resolves with status and body text */
  upload: (url: string, form: FormData, onProgress?: (fraction: number) => void) => Promise<{ status: number; body: string }>
}

export const browserHttp: Http = {
  fetch: (url, init) => fetch(url, init),
  upload: (url, form, onProgress) =>
    new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', url)
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress?.(e.loaded / e.total)
      }
      xhr.onload = () => resolve({ status: xhr.status, body: xhr.responseText })
      xhr.onerror = () => reject(new ApiError(0, 'network error during upload'))
      xhr.send(form)
    }),
}

export interface ApiOptions {
  http?: Http
  /** overrides VITE_API_URL (tests) */
  base?: string
}

export function apiBase(override?: string): string {
  const raw = override ?? import.meta.env.VITE_API_URL ?? ''
  return raw.trim().replace(/\/+$/, '')
}

export function apiConfigured(override?: string): boolean {
  return apiBase(override) !== ''
}

function base(opts?: ApiOptions): string {
  const b = apiBase(opts?.base)
  if (!b) throw new ApiNotConfigured()
  return b
}

async function readJson(res: { status: number; body: string }, what: string): Promise<unknown> {
  if (res.status < 200 || res.status >= 300) {
    let detail = res.body.slice(0, 200)
    try {
      const j = JSON.parse(res.body) as { detail?: unknown }
      if (typeof j.detail === 'string') detail = j.detail
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, `${what} failed (HTTP ${res.status})${detail ? `: ${detail}` : ''}`)
  }
  try {
    return JSON.parse(res.body) as unknown
  } catch {
    throw new ApiError(res.status, `${what}: the server did not return JSON`)
  }
}

export async function apiGet(path: string, what: string, opts?: ApiOptions): Promise<unknown> {
  const http = opts?.http ?? browserHttp
  let res: Response
  try {
    res = await http.fetch(`${base(opts)}${path}`, { headers: { Accept: 'application/json' } })
  } catch (e) {
    if (e instanceof ApiNotConfigured) throw e
    throw new ApiError(0, `${what}: could not reach the analysis server`)
  }
  return readJson({ status: res.status, body: await res.text() }, what)
}

export async function apiPost(path: string, body: unknown, what: string, opts?: ApiOptions): Promise<unknown> {
  const http = opts?.http ?? browserHttp
  let res: Response
  try {
    res = await http.fetch(`${base(opts)}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(body),
    })
  } catch (e) {
    if (e instanceof ApiNotConfigured) throw e
    throw new ApiError(0, `${what}: could not reach the analysis server`)
  }
  return readJson({ status: res.status, body: await res.text() }, what)
}

export async function apiUpload(path: string, form: FormData, what: string, onProgress: ((f: number) => void) | undefined, opts?: ApiOptions): Promise<unknown> {
  const http = opts?.http ?? browserHttp
  const url = `${base(opts)}${path}`
  return readJson(await http.upload(url, form, onProgress), what)
}
