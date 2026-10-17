import type { ReactNode } from 'react'
import { AlertTriangle, Inbox } from 'lucide-react'

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`skeleton rounded-xl ${className}`} aria-hidden="true" />
}

export function PageSkeleton() {
  return (
    <div className="min-h-screen bg-bg p-6" role="status" aria-live="polite">
      <span className="sr-only">Loading the analyst desk…</span>
      <Skeleton className="mb-6 h-12 w-full" />
      <div className="grid gap-4 lg:grid-cols-[1fr_1fr_360px]">
        <Skeleton className="h-72" />
        <Skeleton className="h-72" />
        <Skeleton className="h-[30rem] lg:row-span-2" />
        <Skeleton className="h-40 lg:col-span-2" />
      </div>
    </div>
  )
}

export function ErrorState({ title, detail, children }: { title: string; detail?: string; children?: ReactNode }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-2 rounded-(--radius-card) border border-danger/40 bg-danger/5 p-5">
      <div className="flex items-center gap-2 font-semibold text-text">
        <AlertTriangle className="size-4 text-danger" aria-hidden="true" />
        {title}
      </div>
      {detail && <p className="font-mono text-xs break-all text-muted">{detail}</p>}
      {children}
    </div>
  )
}

export function EmptyState({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
      <div className="grid size-12 place-items-center rounded-full border border-line bg-surface-2 text-muted">
        {icon ?? <Inbox className="size-5" aria-hidden="true" />}
      </div>
      <p className="font-display text-lg font-semibold text-text">{title}</p>
      {children && <div className="max-w-sm text-sm text-muted">{children}</div>}
    </div>
  )
}
