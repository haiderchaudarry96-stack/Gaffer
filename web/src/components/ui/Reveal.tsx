import type { ReactNode } from 'react'
import { m } from 'motion/react'
import { usePrefersReducedMotion } from '../../lib/hooks'

/** Fade + 24 px rise when scrolled into view, once (UI_DESIGN §4). */
export default function Reveal({
  children,
  delay = 0,
  className,
}: {
  children: ReactNode
  delay?: number
  className?: string
}) {
  const reduced = usePrefersReducedMotion()
  // with reduced motion, content is simply there: no hidden initial state to wait on
  if (reduced) return <div className={className}>{children}</div>
  return (
    <m.div
      className={className}
      initial={{ opacity: 0, y: 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '0px 0px -10% 0px' }}
      transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1], delay }}
    >
      {children}
    </m.div>
  )
}
