import { useId, useState, type ReactNode } from 'react'
import { AnimatePresence, m } from 'motion/react'
import { ChevronDown } from 'lucide-react'

/**
 * An accessible show/hide block. The panel fades and rises in (opacity + transform only;
 * the height change itself is instant, so nothing animates layout).
 */
export default function Disclosure({
  summary,
  children,
  className = '',
  summaryClassName = '',
}: {
  summary: ReactNode
  children: ReactNode
  className?: string
  summaryClassName?: string
}) {
  const [open, setOpen] = useState(false)
  const id = useId()
  return (
    <div className={className}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
        className={`flex w-full items-center justify-between gap-4 text-left ${summaryClassName}`}
      >
        {summary}
        <ChevronDown className={`size-5 shrink-0 transition-transform duration-300 ${open ? 'rotate-180' : ''}`} aria-hidden="true" />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <m.div
            id={id}
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
          >
            {children}
          </m.div>
        )}
      </AnimatePresence>
    </div>
  )
}

/** "Read the small print": every caveat of a section, one click away. */
export function SmallPrint({ items }: { items: ReactNode[] }) {
  return (
    <Disclosure
      className="mt-10 border-t border-line pt-4"
      summaryClassName="text-sm font-medium text-muted hover:text-text"
      summary={<span>Read the small print</span>}
    >
      <ul className="mt-4 max-w-3xl list-disc space-y-2 pl-5 text-sm leading-relaxed text-muted">
        {items.map((it, i) => (
          <li key={i}>{it}</li>
        ))}
      </ul>
    </Disclosure>
  )
}
