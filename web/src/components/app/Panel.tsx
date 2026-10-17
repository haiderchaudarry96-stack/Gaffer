import type { ReactNode } from 'react'

export default function Panel({
  title,
  id,
  actions,
  children,
  className = '',
}: {
  title: string
  id: string
  actions?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section aria-labelledby={id} className={`flex min-w-0 flex-col rounded-(--radius-card) border border-line bg-surface ${className}`}>
      <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
        <h2 id={id} className="font-sans text-sm font-semibold tracking-normal text-text">
          {title}
        </h2>
        {actions}
      </header>
      <div className="min-h-0 flex-1">{children}</div>
    </section>
  )
}
