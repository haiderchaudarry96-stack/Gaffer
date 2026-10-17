import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { AnimatePresence, m } from 'motion/react'
import { Send, X } from 'lucide-react'
import Mascot from '../mascot/Mascot'
import { apiConfigured, ApiNotConfigured } from '../../data/api'
import { sendChat, type ChatTurn } from '../../data/chat'

const NOT_CONNECTED = 'The agent runs in Gaffer’s Python backend on Amazon Bedrock; answers go live when this site is connected to it.'

interface Message extends ChatTurn {
  note?: boolean
}

/**
 * The agent's chat: a round mascot button that expands into a chat box on hover, keyboard focus
 * or tap, and collapses when the pointer leaves with an empty input, or on Escape.
 * Sending goes through src/data/chat.ts (POST /api/chat); without a backend it says so.
 */
export default function ChatFab({ matchId, suggestions }: { matchId: string; suggestions: string[] }) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [sending, setSending] = useState(false)
  const id = useId()
  const buttonRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const closeTimer = useRef<number | null>(null)
  const ignoreFocus = useRef(false)
  const connected = apiConfigured()

  const cancelClose = () => {
    if (closeTimer.current) window.clearTimeout(closeTimer.current)
    closeTimer.current = null
  }
  const close = (returnFocus: boolean) => {
    cancelClose()
    setOpen(false)
    if (returnFocus) {
      ignoreFocus.current = true // focusing the button again must not reopen the box
      buttonRef.current?.focus()
      window.setTimeout(() => (ignoreFocus.current = false), 0)
    }
  }
  const openBox = (focusInput: boolean) => {
    cancelClose()
    setOpen(true)
    if (focusInput) window.setTimeout(() => inputRef.current?.focus(), 30)
  }

  // tap or click outside closes it (touch has no "pointer leaves")
  useEffect(() => {
    if (!open) return
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node
      if (!panelRef.current?.contains(t) && !buttonRef.current?.contains(t) && text.trim() === '') setOpen(false)
    }
    window.addEventListener('pointerdown', onDown)
    return () => window.removeEventListener('pointerdown', onDown)
  }, [open, text])

  useEffect(() => cancelClose, [])

  // focus trap + Escape while open
  const onPanelKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.stopPropagation()
      close(true)
      return
    }
    if (e.key !== 'Tab' || !panelRef.current) return
    const items = [...panelRef.current.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled])')]
    if (!items.length) return
    const first = items[0]
    const last = items[items.length - 1]
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
  }

  const ask = async (question: string) => {
    const q = question.trim()
    if (!q || sending) return
    const history: ChatTurn[] = messages.filter((x) => !x.note).map(({ role, text: t }) => ({ role, text: t }))
    setMessages((ms) => [...ms, { role: 'user', text: q }])
    setText('')
    if (!connected) {
      setMessages((ms) => [...ms, { role: 'assistant', text: 'Not sent: this demo build is not connected to the agent.', note: true }])
      return
    }
    setSending(true)
    try {
      const a = await sendChat({ match_id: matchId, question: q, history })
      setMessages((ms) => [...ms, { role: 'assistant', text: a.answer }])
    } catch (err) {
      const msg = err instanceof ApiNotConfigured ? 'Not sent: this demo build is not connected to the agent.' : `Could not reach the agent (${err instanceof Error ? err.message : 'error'}).`
      setMessages((ms) => [...ms, { role: 'assistant', text: msg, note: true }])
    } finally {
      setSending(false)
    }
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    void ask(text)
  }

  return (
    <div
      className="fixed right-4 bottom-4 z-40 sm:right-6 sm:bottom-6"
      onPointerEnter={(e) => e.pointerType === 'mouse' && openBox(false)}
      onPointerLeave={(e) => {
        if (e.pointerType !== 'mouse' || text.trim() !== '' || sending) return
        cancelClose()
        closeTimer.current = window.setTimeout(() => setOpen(false), 280)
      }}
    >
      <AnimatePresence>
        {open && (
          <m.div
            ref={panelRef}
            id={`${id}-panel`}
            role="dialog"
            aria-labelledby={`${id}-title`}
            onKeyDown={onPanelKey}
            initial={{ opacity: 0, scale: 0.2 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.2 }}
            transition={{ type: 'spring', stiffness: 380, damping: 32 }}
            style={{ transformOrigin: 'bottom right' }}
            className="absolute right-0 bottom-0 flex h-[min(30rem,calc(100dvh-6rem))] w-[min(22.5rem,calc(100vw-2rem))] flex-col overflow-hidden rounded-3xl border border-line bg-surface shadow-[0_24px_60px_-20px_rgba(7,13,10,0.45)]"
          >
            <header className="flex items-center gap-3 border-b border-line px-4 py-3">
              <span className="grid size-11 place-items-center rounded-full bg-surface-2">
                <Mascot size={40} />
              </span>
              <div className="min-w-0 flex-1">
                <p id={`${id}-title`} className="font-display text-base font-semibold text-text">
                  Gaffer
                </p>
                <p className="text-xs text-muted">Your tactical analyst</p>
              </div>
              <button type="button" onClick={() => close(true)} className="grid size-9 place-items-center rounded-full text-muted hover:bg-surface-2 hover:text-text" aria-label="Close chat">
                <X className="size-4" aria-hidden="true" />
              </button>
            </header>
            <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4" aria-live="polite">
              {!connected && <p className="rounded-2xl border border-line bg-bg px-3 py-2.5 text-sm leading-relaxed text-muted">{NOT_CONNECTED}</p>}
              {messages.map((msg, i) => (
                <p
                  key={i}
                  className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm leading-relaxed ${msg.role === 'user' ? 'ml-auto bg-accent text-on-accent' : msg.note ? 'border border-warn/40 bg-warn/5 text-text' : 'bg-surface-2 text-text'}`}
                >
                  {msg.text}
                </p>
              ))}
              {sending && <p className="text-sm text-muted">Gaffer is checking…</p>}
              {messages.length === 0 && suggestions.length > 0 && (
                <div className="space-y-2 pt-1">
                  <p className="text-xs text-muted">Try asking</p>
                  <ul className="flex flex-col items-start gap-2">
                    {suggestions.map((s) => (
                      <li key={s}>
                        <button type="button" onClick={() => void ask(s)} className="rounded-full border border-line px-3 py-1.5 text-left text-sm text-text hover:border-text">
                          {s}
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
            <form onSubmit={submit} className="flex gap-2 border-t border-line p-3">
              <label htmlFor={`${id}-q`} className="sr-only">
                Ask Gaffer about this analysis
              </label>
              <input
                ref={inputRef}
                id={`${id}-q`}
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Ask Gaffer about this analysis"
                autoComplete="off"
                className="h-11 min-w-0 flex-1 rounded-full border border-line bg-bg px-4 text-sm text-text placeholder:text-muted"
              />
              <button type="submit" disabled={!text.trim() || sending} className="grid size-11 place-items-center rounded-full bg-accent text-on-accent disabled:opacity-40" aria-label="Send question">
                <Send className="size-4" aria-hidden="true" />
              </button>
            </form>
          </m.div>
        )}
      </AnimatePresence>

      <m.button
        ref={buttonRef}
        type="button"
        aria-label="Ask Gaffer, your tactical analyst"
        aria-expanded={open}
        aria-controls={`${id}-panel`}
        onFocus={() => !ignoreFocus.current && !open && openBox(true)}
        onClick={() => (open ? close(true) : openBox(true))}
        animate={{ opacity: open ? 0 : 1, scale: open ? 0.6 : 1 }}
        transition={{ duration: 0.2 }}
        style={{ pointerEvents: open ? 'none' : 'auto' }}
        className="relative grid size-16 place-items-center rounded-full border border-line bg-surface shadow-[0_10px_30px_-10px_rgba(7,13,10,0.45)] ring-4 ring-accent/35"
      >
        <Mascot size={52} />
        {/* small chat bubble with three dots */}
        <span className="absolute -right-1 -bottom-1 flex h-5 items-center gap-0.5 rounded-full border border-line bg-surface px-1.5 shadow" aria-hidden="true">
          <span className="size-1 rounded-full bg-text" />
          <span className="size-1 rounded-full bg-text" />
          <span className="size-1 rounded-full bg-text" />
        </span>
      </m.button>
    </div>
  )
}
