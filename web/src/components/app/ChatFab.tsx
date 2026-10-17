import { useEffect, useId, useRef, useState } from 'react'
import { AnimatePresence, m } from 'motion/react'
import { MessageSquare, Send, X } from 'lucide-react'

/** Chat answers through the agent's tools, so it needs the backend: a small button and panel. */
export default function ChatFab() {
  const [open, setOpen] = useState(false)
  const id = useId()
  const buttonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        buttonRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  return (
    <div className="fixed right-4 bottom-4 z-40 flex flex-col items-end gap-3 sm:right-5 sm:bottom-5">
      <AnimatePresence>
        {open && (
          <m.div
            id={`${id}-panel`}
            role="region"
            aria-label="Ask Gaffer"
            initial={{ opacity: 0, y: 12, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 12, scale: 0.97 }}
            transition={{ duration: 0.2 }}
            className="w-[min(22rem,calc(100vw-2rem))] origin-bottom-right rounded-(--radius-card) border border-line bg-surface p-4 shadow-2xl"
          >
            <p className="mb-3 font-semibold text-text">Ask Gaffer</p>
            <form className="flex gap-2" onSubmit={(e) => e.preventDefault()}>
              <label htmlFor={`${id}-q`} className="sr-only">
                Question about the match
              </label>
              <input
                id={`${id}-q`}
                disabled
                placeholder="Why did White go to a back three?"
                aria-describedby={`${id}-note`}
                className="h-10 min-w-0 flex-1 rounded-full border border-line bg-bg px-4 text-sm text-text placeholder:text-muted disabled:cursor-not-allowed"
              />
              <button type="submit" disabled className="grid size-10 place-items-center rounded-full bg-surface-2 text-muted" aria-label="Send">
                <Send className="size-4" aria-hidden="true" />
              </button>
            </form>
            <p id={`${id}-note`} className="mt-3 text-sm leading-relaxed text-muted">
              The agent runs in Gaffer’s Python backend on AWS Bedrock; chat goes live when this site is connected to that
              backend.
            </p>
          </m.div>
        )}
      </AnimatePresence>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls={`${id}-panel`}
        aria-label={open ? 'Close chat' : 'Ask Gaffer'}
        title="Ask Gaffer"
        className="grid size-12 place-items-center rounded-full border border-line bg-surface-2 text-text shadow-xl hover:bg-line"
      >
        {open ? <X className="size-5" aria-hidden="true" /> : <MessageSquare className="size-5" aria-hidden="true" />}
      </button>
    </div>
  )
}
