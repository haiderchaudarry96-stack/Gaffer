import type { ReactNode } from 'react'
import Reveal from '../ui/Reveal'

/** One idea per section: an eyebrow, one big statement, one short line. */
export default function Section({
  id,
  eyebrow,
  title,
  line,
  children,
  className = '',
}: {
  id: string
  eyebrow: string
  title: ReactNode
  line?: ReactNode
  children?: ReactNode
  className?: string
}) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className={`scroll-mt-20 py-24 sm:py-32 ${className}`}>
      <div className="mx-auto max-w-7xl px-4 sm:px-6">
        <Reveal>
          <p className="mb-4 font-mono text-xs tracking-widest text-accent-ink uppercase">{eyebrow}</p>
          <h2 id={`${id}-title`} className="max-w-4xl text-4xl leading-[1.05] font-bold text-text sm:text-6xl">
            {title}
          </h2>
          {line && <p className="mt-5 max-w-2xl text-lg text-muted sm:text-xl">{line}</p>}
        </Reveal>
        {children}
      </div>
    </section>
  )
}
