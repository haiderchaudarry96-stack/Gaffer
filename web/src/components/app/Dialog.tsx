import { useEffect, useRef, type ReactNode } from 'react'
import { X } from 'lucide-react'

/** Native modal dialog: focus trap, Esc to close and inert background come from the browser. */
export default function Dialog({
  open,
  onClose,
  title,
  children,
  wide = false,
}: {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  wide?: boolean
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (open && !d.open) d.showModal()
    if (!open && d.open) d.close()
  }, [open])

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      aria-labelledby="dialog-title"
      className={`m-auto max-h-[90vh] w-[calc(100%-2rem)] overflow-hidden rounded-(--radius-card) border border-line bg-surface p-0 text-text backdrop:bg-bg/80 backdrop:backdrop-blur-sm ${wide ? 'max-w-5xl' : 'max-w-3xl'}`}
    >
      {open && (
        <div className="flex max-h-[90vh] flex-col">
          <header className="flex items-center justify-between gap-3 border-b border-line px-5 py-3">
            <h2 id="dialog-title" className="font-sans text-base font-semibold tracking-normal">
              {title}
            </h2>
            <button
              type="button"
              onClick={onClose}
              className="grid size-9 place-items-center rounded-full text-muted hover:bg-surface-2 hover:text-text"
              aria-label="Close"
            >
              <X className="size-4" aria-hidden="true" />
            </button>
          </header>
          <div className="overflow-y-auto">{children}</div>
        </div>
      )}
    </dialog>
  )
}
