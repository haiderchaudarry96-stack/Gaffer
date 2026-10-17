import { useEffect, useRef, type ReactNode } from 'react'
import { m } from 'motion/react'
import { X } from 'lucide-react'

/**
 * Native modal dialog: focus trap, Esc to close and an inert background come from the browser.
 * variant "drawer" slides in from the right edge.
 */
export default function Dialog({
  open,
  onClose,
  title,
  children,
  wide = false,
  variant = 'center',
  icon,
}: {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  wide?: boolean
  variant?: 'center' | 'drawer'
  /** shown before the title, e.g. the mascot */
  icon?: ReactNode
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (open && !d.open) d.showModal()
    if (!open && d.open) d.close()
  }, [open])

  const shell =
    variant === 'drawer'
      ? 'm-0 ml-auto h-dvh max-h-dvh w-[min(34rem,100%)] rounded-none border-0 border-l'
      : `m-auto max-h-[90vh] w-[calc(100%-2rem)] rounded-(--radius-card) border ${wide ? 'max-w-5xl' : 'max-w-3xl'}`

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      aria-labelledby="dialog-title"
      className={`overflow-hidden border-line bg-surface p-0 text-text backdrop:bg-[rgba(11,21,16,0.38)] backdrop:backdrop-blur-[2px] ${shell}`}
    >
      {open && (
        <m.div
          className={`flex flex-col ${variant === 'drawer' ? 'h-dvh' : 'max-h-[90vh]'}`}
          initial={variant === 'drawer' ? { x: 48, opacity: 0 } : { y: 12, opacity: 0 }}
          animate={{ x: 0, y: 0, opacity: 1 }}
          transition={{ type: 'spring', stiffness: 320, damping: 32 }}
        >
          <header className="flex items-center justify-between gap-3 border-b border-line px-5 py-4">
            <h2 id="dialog-title" className="flex items-center gap-3 font-sans text-lg font-semibold tracking-normal">
              {icon && (
                <span className="grid size-11 shrink-0 place-items-center rounded-full bg-surface-2" aria-hidden="true">
                  {icon}
                </span>
              )}
              {title}
            </h2>
            <button
              type="button"
              onClick={onClose}
              className="grid size-10 place-items-center rounded-full text-muted hover:bg-surface-2 hover:text-text"
              aria-label="Close"
            >
              <X className="size-5" aria-hidden="true" />
            </button>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
        </m.div>
      )}
    </dialog>
  )
}
