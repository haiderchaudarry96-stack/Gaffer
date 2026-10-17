import { useId } from 'react'
import { Pause, Play } from 'lucide-react'
import type { PlaybackClock } from '../../lib/clock'
import { useClockTime } from '../../lib/hooks'
import { formatClock } from '../../data/time'
import type { Transport } from './transport'

const RATES = [1, 2, 4]

export default function PlaybackBar({ clock, transport, hasVideo }: { clock: PlaybackClock; transport: Transport; hasVideo: boolean }) {
  const t = useClockTime(clock, 10)
  const rangeId = useId()
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-(--radius-card) border border-line bg-surface px-4 py-3">
      <button
        type="button"
        onClick={transport.toggle}
        className="grid size-10 shrink-0 place-items-center rounded-full bg-accent text-bg"
        aria-label={transport.playing ? 'Pause' : 'Play'}
      >
        {transport.playing ? <Pause className="size-4" aria-hidden="true" /> : <Play className="size-4 translate-x-px" aria-hidden="true" />}
      </button>
      <span className="font-mono text-sm text-text tabular">{formatClock(t)}</span>
      <label htmlFor={rangeId} className="sr-only">
        Match time
      </label>
      <input
        id={rangeId}
        type="range"
        min={clock.min}
        max={clock.max}
        step={0.5}
        value={t}
        onChange={(e) => transport.seek(Number(e.target.value))}
        aria-valuetext={formatClock(t)}
        className="h-1.5 min-w-40 flex-1 cursor-pointer accent-[var(--accent)]"
      />
      <span className="font-mono text-sm text-muted tabular">{formatClock(clock.max)}</span>
      <div role="group" aria-label="Playback speed" className="flex rounded-full border border-line p-0.5">
        {RATES.map((r) => (
          <button
            key={r}
            type="button"
            onClick={() => transport.setRate(r)}
            aria-pressed={transport.rate === r}
            className={`rounded-full px-2.5 py-1 font-mono text-xs ${transport.rate === r ? 'bg-surface-2 text-text' : 'text-muted hover:text-text'}`}
          >
            {r}×
          </button>
        ))}
      </div>
      <span className="w-full text-[11px] text-muted sm:w-auto">
        {hasVideo ? 'Time from your video' : 'Time from the stored positions (2 samples per second, interpolated)'}
      </span>
    </div>
  )
}
