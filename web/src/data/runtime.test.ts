/** The "Live on AWS" data: parsing /api/runtime and the exact card text (no server, no AWS). */
import { describe, expect, it, vi } from 'vitest'
import { ApiNotConfigured, type Http } from './api'
import { validateStatus } from './analysis'
import { ago, describeRuntime, loadRuntime, parseRuntime, uptime } from './runtime'

const ON_AWS = {
  checked_utc: '2026-10-24T12:03:00Z',
  aws: { running_on_aws: true, platform: 'Amazon EC2', message: null, instance_type: 'm7i-flex.large', availability_zone: 'ap-southeast-2a', region: 'ap-southeast-2' },
  bedrock: { configured: true, model_id: 'global.amazon.nova-2-lite-v1:0', model_label: 'Nova 2 Lite', region: 'ap-southeast-2', calls_today: 12, calls_cap_today: 300, last_call_utc: '2026-10-24T12:00:00Z' },
  app: { opencv_version: '5.0.0', rules_fingerprint: 'ca4ff9bbf7b01c6c', uptime_s: 7260, storage: 'local' },
}
const OFF_AWS = {
  ...ON_AWS,
  aws: { running_on_aws: false, platform: null, message: 'not running on AWS', instance_type: null, availability_zone: null, region: null },
  bedrock: { ...ON_AWS.bedrock, configured: false, calls_today: 0, last_call_utc: null },
}

describe('runtime report', () => {
  it('writes the card line from real values only', () => {
    const lines = describeRuntime(parseRuntime(ON_AWS))
    expect(lines.running).toBe(true)
    expect(lines.headline).toBe('Running now on Amazon EC2 m7i-flex.large · ap-southeast-2a · Bedrock Nova 2 Lite · last call 3 min ago · 12 calls today')
  })

  it('says "not running on AWS" off AWS and never invents an instance', () => {
    const lines = describeRuntime(parseRuntime(OFF_AWS))
    expect(lines.running).toBe(false)
    expect(lines.headline).toBe('Not running on AWS · Bedrock not configured on this server')
    expect(lines.headline).not.toMatch(/EC2|m7i|ap-southeast/)
  })

  it('says "unavailable" for a field the server could not read', () => {
    const info = parseRuntime({ ...ON_AWS, aws: { ...ON_AWS.aws, instance_type: null }, bedrock: { ...ON_AWS.bedrock, calls_today: null, last_call_utc: null } })
    const line = describeRuntime(info).headline
    expect(line).toContain('instance type unavailable')
    expect(line).toContain('last call unavailable')
    expect(line).toContain('calls today unavailable')
  })

  it('handles a day with no Bedrock call yet', () => {
    const info = parseRuntime({ ...ON_AWS, bedrock: { ...ON_AWS.bedrock, calls_today: 0, last_call_utc: null } })
    expect(describeRuntime(info).headline).toContain('Bedrock Nova 2 Lite · no calls yet today')
  })

  it('rejects a report that is not the documented shape', () => {
    expect(() => parseRuntime({})).toThrow(/incomplete/)
    expect(() => parseRuntime(null)).toThrow(/incomplete/)
  })

  it('formats ages and uptime', () => {
    expect(ago('2026-10-24T12:02:40Z', '2026-10-24T12:03:00Z')).toBe('just now')
    expect(ago('2026-10-24T09:00:00Z', '2026-10-24T12:03:00Z')).toBe('3 h 3 min ago')
    expect(ago(null, '2026-10-24T12:03:00Z')).toBeNull()
    expect(uptime(30)).toBe('under a minute')
    expect(uptime(7260)).toBe('2 h 1 min')
    expect(uptime(null)).toBeNull()
  })

  it('loads from /api/runtime, and a build without a server says so', async () => {
    const http: Http = {
      fetch: vi.fn(async () => new Response(JSON.stringify(ON_AWS), { status: 200 })),
      upload: vi.fn(),
    }
    const info = await loadRuntime({ http, base: 'https://api.test' })
    expect(info.aws.instanceType).toBe('m7i-flex.large')
    expect(http.fetch).toHaveBeenCalledWith('https://api.test/api/runtime', expect.anything())
    await expect(loadRuntime({ http, base: '' })).rejects.toBeInstanceOf(ApiNotConfigured)
  })
})

describe('queue position', () => {
  const base = { id: 'an_1', stage: 'detecting', progress: 0, eta_s: null }
  it('reports how many analyses are ahead of a queued one, and only then', () => {
    expect(validateStatus({ ...base, status: 'queued', queue_position: 2 }).queue_ahead).toBe(2)
    expect(validateStatus({ ...base, status: 'queued' }).queue_ahead).toBeNull()
    expect(validateStatus({ ...base, status: 'running', queue_position: 0 }).queue_ahead).toBeNull()
  })
})
