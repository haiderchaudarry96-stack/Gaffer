/**
 * What the server is running on right now (`GET /api/runtime`, docs/API.md): the data behind the
 * landing page's "Live on AWS" card. Real values only: a field the server could not read is null
 * and the card says "unavailable" for it.
 */
import { apiGet, type ApiOptions } from './api'

export interface RuntimeInfo {
  checkedUtc: string | null
  aws: { running: boolean; platform: string | null; instanceType: string | null; availabilityZone: string | null; region: string | null }
  bedrock: { configured: boolean; modelLabel: string | null; callsToday: number | null; lastCallUtc: string | null }
  app: { opencv: string | null; fingerprint: string | null; uptimeS: number | null }
}

function rec(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' ? (v as Record<string, unknown>) : {}
}
const s = (v: unknown): string | null => (typeof v === 'string' && v !== '' ? v : null)
const n = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)

export function parseRuntime(raw: unknown): RuntimeInfo {
  const r = rec(raw)
  const aws = rec(r.aws)
  const b = rec(r.bedrock)
  const app = rec(r.app)
  if (typeof aws.running_on_aws !== 'boolean') throw new Error('The runtime report is incomplete')
  return {
    checkedUtc: s(r.checked_utc),
    aws: {
      running: aws.running_on_aws,
      platform: s(aws.platform),
      instanceType: s(aws.instance_type),
      availabilityZone: s(aws.availability_zone),
      region: s(aws.region),
    },
    bedrock: {
      configured: b.configured === true,
      modelLabel: s(b.model_label) ?? s(b.model_id),
      callsToday: n(b.calls_today),
      lastCallUtc: s(b.last_call_utc),
    },
    app: { opencv: s(app.opencv_version), fingerprint: s(app.rules_fingerprint), uptimeS: n(app.uptime_s) },
  }
}

export async function loadRuntime(opts?: ApiOptions): Promise<RuntimeInfo> {
  return parseRuntime(await apiGet('/api/runtime', 'Runtime report', opts))
}

/** "3 min ago", "just now", "2 h 5 min ago"; the age is measured on the server's clock. */
export function ago(fromUtc: string | null, nowUtc: string | null): string | null {
  if (!fromUtc || !nowUtc) return null
  const secs = (Date.parse(nowUtc) - Date.parse(fromUtc)) / 1000
  if (!Number.isFinite(secs)) return null
  if (secs < 45) return 'just now'
  const mins = Math.round(secs / 60)
  if (mins < 60) return `${mins} min ago`
  const h = Math.floor(mins / 60)
  const m = mins % 60
  if (h < 48) return m ? `${h} h ${m} min ago` : `${h} h ago`
  return `${Math.floor(h / 24)} days ago`
}

export function uptime(secs: number | null): string | null {
  if (secs == null) return null
  if (secs < 90) return 'under a minute'
  const mins = Math.round(secs / 60)
  if (mins < 60) return `${mins} min`
  const h = Math.floor(mins / 60)
  if (h < 48) return `${h} h ${mins % 60} min`
  return `${Math.floor(h / 24)} days ${h % 24} h`
}

export interface RuntimeLines {
  /** the one-line headline */
  headline: string
  running: boolean
}

/** The card text. Every piece is a real value, or the word "unavailable". */
export function describeRuntime(info: RuntimeInfo): RuntimeLines {
  const u = 'unavailable'
  const { aws, bedrock } = info
  const bedrockParts: string[] = []
  if (!bedrock.configured) {
    bedrockParts.push('Bedrock not configured on this server')
  } else {
    bedrockParts.push(`Bedrock ${bedrock.modelLabel ?? u}`)
    if (bedrock.callsToday === 0 && !bedrock.lastCallUtc) {
      bedrockParts.push('no calls yet today')
    } else {
      const last = ago(bedrock.lastCallUtc, info.checkedUtc)
      bedrockParts.push(last ? `last call ${last}` : `last call ${u}`)
      bedrockParts.push(bedrock.callsToday == null ? `calls today ${u}` : `${bedrock.callsToday} ${bedrock.callsToday === 1 ? 'call' : 'calls'} today`)
    }
  }
  if (!aws.running) {
    return { headline: ['Not running on AWS', ...bedrockParts].join(' · '), running: false }
  }
  const where = [aws.platform ?? 'AWS', aws.instanceType ?? `instance type ${u}`, aws.availabilityZone ?? aws.region ?? `zone ${u}`]
  return {
    headline: `Running now on ${[where[0], where[1]].join(' ')} · ${where[2]} · ${bedrockParts.join(' · ')}`,
    running: true,
  }
}
