import { useEffect, useState } from 'react'
import Reveal from '../ui/Reveal'
import { ApiNotConfigured } from '../../data/api'
import { ago, describeRuntime, loadRuntime, uptime, type RuntimeInfo } from '../../data/runtime'

const REFRESH_MS = 60_000

type State = { kind: 'loading' } | { kind: 'unavailable'; why: string } | { kind: 'ready'; info: RuntimeInfo }

/**
 * "Live on AWS": what this server is running on right now, read from `GET /api/runtime` (EC2
 * instance metadata, the app's own Bedrock counters). Refreshes every minute; a value the server
 * could not read says "unavailable", and a copy of the site without a server says so.
 */
export default function LiveOnAws() {
  const [state, setState] = useState<State>({ kind: 'loading' })

  useEffect(() => {
    let alive = true
    const load = () =>
      loadRuntime().then(
        (info) => alive && setState({ kind: 'ready', info }),
        (err: unknown) =>
          alive &&
          setState({
            kind: 'unavailable',
            why: err instanceof ApiNotConfigured ? 'This copy of the site is not connected to a Gaffer server.' : 'The server did not answer just now.',
          }),
      )
    void load()
    const timer = window.setInterval(() => void load(), REFRESH_MS)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [])

  const lines = state.kind === 'ready' ? describeRuntime(state.info) : null
  const live = lines?.running === true
  return (
    <Reveal className="mt-8">
      <div data-testid="live-on-aws" className="rounded-(--radius-card) border border-line bg-surface p-6 sm:p-7">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span
            aria-hidden="true"
            className={`size-2.5 rounded-full ${live ? 'live-dot bg-accent' : state.kind === 'loading' ? 'skeleton' : 'bg-muted/60'}`}
          />
          <h3 className="font-sans text-sm font-semibold tracking-wide text-text uppercase">Live on AWS</h3>
          <span className="font-mono text-xs text-muted">refreshes every minute</span>
        </div>
        {state.kind === 'loading' && <p className="mt-4 text-muted">Reading the server&apos;s status…</p>}
        {state.kind === 'unavailable' && (
          <p className="mt-4 text-lg text-text">
            Live status unavailable. <span className="text-muted">{state.why}</span>
          </p>
        )}
        {state.kind === 'ready' && lines && (
          <>
            <p aria-live="polite" className="mt-4 text-lg leading-relaxed text-text sm:text-xl">
              {lines.headline}
            </p>
            <Details info={state.info} />
          </>
        )}
        <p className="mt-5 text-xs leading-relaxed text-muted">
          Read from this server&apos;s own metadata service and usage counters. No instance ID, account ID, address, key or prompt is shown.
        </p>
      </div>
    </Reveal>
  )
}

function Details({ info }: { info: RuntimeInfo }) {
  const u = 'unavailable'
  const { aws, bedrock, app } = info
  const last = ago(bedrock.lastCallUtc, info.checkedUtc)
  const groups: { label: string; rows: [string, string][] }[] = [
    {
      label: 'Compute',
      rows: aws.running
        ? [
            ['Service', aws.platform ?? u],
            ['Instance type', aws.instanceType ?? u],
            ['Zone', aws.availabilityZone ?? u],
            ['Region', aws.region ?? u],
          ]
        : [['Service', 'not running on AWS']],
    },
    {
      label: 'Amazon Bedrock',
      rows: bedrock.configured
        ? [
            ['Model', bedrock.modelLabel ?? u],
            ['Calls today', bedrock.callsToday == null ? u : String(bedrock.callsToday)],
            ['Last call', bedrock.lastCallUtc ? (last ?? u) : bedrock.callsToday === 0 ? 'none yet today' : u],
          ]
        : [['Model', 'not configured here']],
    },
    {
      label: 'App',
      rows: [
        ['OpenCV', app.opencv ?? u],
        ['Rules', app.fingerprint ?? u],
        ['Uptime', uptime(app.uptimeS) ?? u],
      ],
    },
  ]
  return (
    <dl className="mt-6 grid gap-6 border-t border-line pt-6 sm:grid-cols-3">
      {groups.map((g) => (
        <div key={g.label}>
          <dt className="font-mono text-xs tracking-wide text-muted uppercase">{g.label}</dt>
          <dd className="mt-2 space-y-1">
            {g.rows.map(([k, v]) => (
              <p key={k} className="flex flex-wrap justify-between gap-x-3 text-sm">
                <span className="text-muted">{k}</span>
                <span className="font-mono text-text">{v}</span>
              </p>
            ))}
          </dd>
        </div>
      ))}
    </dl>
  )
}
