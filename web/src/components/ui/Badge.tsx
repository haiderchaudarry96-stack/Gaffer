import type { EventStatus } from '../../data'

const styles: Record<EventStatus | 'pending' | 'approved', string> = {
  confirmed: 'border-accent/50 bg-accent/10 text-accent-ink',
  approved: 'border-accent/50 bg-accent/10 text-accent-ink',
  rejected: 'border-danger/50 bg-danger/10 text-danger',
  uncertain: 'border-warn/50 bg-warn/10 text-warn',
  pending: 'border-warn/50 bg-warn/10 text-warn',
  candidate: 'border-line bg-surface-2 text-muted',
}

const labels: Record<string, string> = { candidate: 'not checked' }

export default function Badge({ status, children }: { status: keyof typeof styles; children?: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 font-mono text-[11px] font-semibold tracking-wide uppercase ${styles[status]}`}
    >
      {children ?? labels[status] ?? status}
    </span>
  )
}
