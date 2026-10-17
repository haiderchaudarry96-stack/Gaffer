import { useEffect, useId, useState } from 'react'
import { Upload } from 'lucide-react'
import { usePrefersReducedMotion } from '../../lib/hooks'

const SEEN_KEY = 'gaffer.uploadHintSeen'

function seenBefore(): boolean {
  try {
    return localStorage.getItem(SEEN_KEY) === '1'
  } catch {
    return false
  }
}

/**
 * Small "Upload for analysis" button with a tooltip. The first time /app opens, a lime dot
 * pulses on it until the first interaction or for 5 s (never with reduced motion).
 */
export default function UploadButton({ onClick }: { onClick: () => void }) {
  const reduced = usePrefersReducedMotion()
  const [hint, setHint] = useState(() => !seenBefore())
  const [tip, setTip] = useState(false)
  const id = useId()

  useEffect(() => {
    if (!hint) return
    const stop = () => {
      setHint(false)
      try {
        localStorage.setItem(SEEN_KEY, '1')
      } catch {
        /* private mode: the dot simply shows again next time */
      }
    }
    const timer = window.setTimeout(stop, 5000)
    window.addEventListener('pointerdown', stop, { once: true })
    window.addEventListener('keydown', stop, { once: true })
    return () => {
      window.clearTimeout(timer)
      window.removeEventListener('pointerdown', stop)
      window.removeEventListener('keydown', stop)
    }
  }, [hint])

  return (
    <span className="relative inline-flex">
      <button
        type="button"
        onClick={onClick}
        aria-describedby={`${id}-tip`}
        onMouseEnter={() => setTip(true)}
        onMouseLeave={() => setTip(false)}
        onFocus={() => setTip(true)}
        onBlur={() => setTip(false)}
        className="relative inline-flex h-9 items-center gap-1.5 rounded-full border border-line px-3 text-sm text-text hover:bg-surface-2"
      >
        <Upload className="size-4" aria-hidden="true" /> Upload for analysis
        {hint && !reduced && (
          <span className="absolute -top-1 -right-1 flex size-3" aria-hidden="true">
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-accent opacity-75" />
            <span className="relative inline-flex size-3 rounded-full border border-white bg-accent" />
          </span>
        )}
      </button>
      <span
        id={`${id}-tip`}
        role="tooltip"
        className={`absolute right-0 bottom-full z-20 mb-2 w-max max-w-60 rounded-lg bg-text px-2.5 py-1.5 text-xs text-bg shadow ${tip ? 'block' : 'sr-only'}`}
      >
        Upload a match video and Gaffer analyses it
      </span>
    </span>
  )
}
