import { useId, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import { Info, RotateCcw, Undo2 } from 'lucide-react'
import type { PixelPoint } from '../../data/analysis'
import StraightenIllustration from './StraightenIllustration'

const NAMES = ['top-left', 'top-right', 'bottom-right', 'bottom-left'] as const
/** where the glowing target waits for each click before the pointer moves (fractions of the frame) */
const HINT: [number, number][] = [
  [0.1, 0.14],
  [0.9, 0.14],
  [0.9, 0.86],
  [0.1, 0.86],
]

const instruction = (n: number) =>
  n < 4 ? `${n + 1}. Click the ${NAMES[n]} corner of the pitch` : 'All 4 points placed. Drag a point to adjust it.'

/**
 * "Show us where the pitch is": the coach clicks 4 points on the first frame of their video.
 * Pointer: click to place, drag to adjust. Keyboard: arrow keys move the glowing target (Shift =
 * bigger steps), Enter places it; a placed point can be focused and moved with the arrow keys.
 */
export default function PitchPoints({
  frameUrl,
  fileName,
  width,
  height,
  points,
  straightDown,
  onChange,
}: {
  frameUrl: string
  fileName: string
  /** video size in pixels; points are stored in these pixels */
  width: number
  height: number
  points: PixelPoint[]
  straightDown: boolean
  onChange: (points: PixelPoint[], straightDown: boolean) => void
}) {
  const id = useId()
  const frameRef = useRef<HTMLDivElement>(null)
  const dragging = useRef<number | null>(null)
  const next = points.length
  const [cursor, setCursor] = useState<PixelPoint | null>(null)
  const [why, setWhy] = useState(false)
  const target = next < 4 ? (cursor ?? { x: HINT[next][0] * width, y: HINT[next][1] * height }) : null

  const toPx = (e: { clientX: number; clientY: number }): PixelPoint => {
    const r = frameRef.current!.getBoundingClientRect()
    const clamp = (v: number, max: number) => Math.min(max, Math.max(0, v))
    return { x: clamp(((e.clientX - r.left) / r.width) * width, width), y: clamp(((e.clientY - r.top) / r.height) * height, height) }
  }
  const place = (p: PixelPoint) => {
    if (points.length >= 4) return
    onChange([...points, p], false)
    setCursor(null)
  }
  const move = (i: number, p: PixelPoint) => onChange(points.map((q, k) => (k === i ? p : q)), false)
  const step = (e: KeyboardEvent) => (e.shiftKey ? 0.05 : 0.01)
  const arrow = (e: KeyboardEvent, p: PixelPoint): PixelPoint | null => {
    const s = step(e)
    const d: Record<string, [number, number]> = { ArrowLeft: [-s, 0], ArrowRight: [s, 0], ArrowUp: [0, -s], ArrowDown: [0, s] }
    const v = d[e.key]
    if (!v) return null
    e.preventDefault()
    return { x: Math.min(width, Math.max(0, p.x + v[0] * width)), y: Math.min(height, Math.max(0, p.y + v[1] * height)) }
  }

  const onFrameKey = (e: KeyboardEvent) => {
    if (!target) return
    const moved = arrow(e, target)
    if (moved) setCursor(moved)
    else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      place(target)
    }
  }
  const onPointKey = (i: number) => (e: KeyboardEvent) => {
    const moved = arrow(e, points[i])
    if (moved) move(i, moved)
  }
  const onPointDown = (i: number) => (e: PointerEvent) => {
    e.stopPropagation()
    dragging.current = i
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }
  const onPointMove = (e: PointerEvent) => {
    if (dragging.current !== null) move(dragging.current, toPx(e))
  }
  const onPointUp = (e: PointerEvent) => {
    e.stopPropagation()
    dragging.current = null
  }
  const pct = (p: PixelPoint) => ({ left: `${(p.x / width) * 100}%`, top: `${(p.y / height) * 100}%` })

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_14rem]">
      <div className="min-w-0">
        <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1">
          <p className="font-display text-xl font-semibold text-text" aria-hidden="true">
            {instruction(next)}
          </p>
          {/* screen readers hear which point is next */}
          <p className="sr-only" aria-live="polite">
            {instruction(next)}
          </p>
        </div>

        {/* A 2D placement widget: arrow keys move the target, Enter places it. role="application"
            tells screen readers to pass the keys through; the instruction is announced above. */}
        {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
        <div
          ref={frameRef}
          role="application"
          // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
          tabIndex={0}
          aria-label={`First frame of ${fileName}. ${instruction(next)}. Use the arrow keys to move the target and Enter to place it.`}
          aria-describedby={`${id}-keys`}
          onKeyDown={onFrameKey}
          onPointerMove={(e) => {
            if (dragging.current !== null) return onPointMove(e)
            // over a placed point the target waits at its suggested spot instead of hiding under it
            const overPoint = (e.target as HTMLElement).closest('button') !== null
            if (next < 4 && e.pointerType === 'mouse') setCursor(overPoint ? null : toPx(e))
          }}
          onPointerLeave={() => dragging.current === null && setCursor(null)}
          onClick={(e) => target && place(toPx(e))}
          className={`relative w-full overflow-hidden rounded-xl border border-line bg-[#0b1510] select-none ${next < 4 ? 'cursor-crosshair' : ''}`}
          style={{ aspectRatio: `${width} / ${height}` }}
        >
          <img src={frameUrl} alt="" className="pointer-events-none absolute inset-0 size-full object-fill" draggable={false} />
          {/* outline of what is placed so far */}
          <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="pointer-events-none absolute inset-0 size-full" aria-hidden="true">
            {points.length > 1 && (
              <polyline
                points={[...points, ...(points.length === 4 ? [points[0]] : [])].map((p) => `${p.x},${p.y}`).join(' ')}
                fill={points.length === 4 ? 'rgba(200,245,66,0.14)' : 'none'}
                stroke="#C8F542"
                strokeWidth={Math.max(2, width / 400)}
                vectorEffect="non-scaling-stroke"
              />
            )}
          </svg>
          {points.map((p, i) => (
            <button
              key={i}
              type="button"
              aria-label={`Pitch corner ${i + 1} of 4 (${NAMES[i]}). Arrow keys move it.`}
              onPointerDown={onPointDown(i)}
              onPointerMove={onPointMove}
              onPointerUp={onPointUp}
              onClick={(e) => e.stopPropagation()}
              onKeyDown={onPointKey(i)}
              className="group absolute z-10 grid size-8 -translate-x-1/2 -translate-y-1/2 cursor-grab touch-none place-items-center rounded-full border-2 border-white bg-accent font-mono text-sm font-bold text-on-accent shadow-lg active:cursor-grabbing"
              style={pct(p)}
            >
              {i + 1}
              <span
                role="tooltip"
                className="pointer-events-none absolute bottom-full left-1/2 mb-2 hidden -translate-x-1/2 rounded-lg bg-text px-2.5 py-1.5 font-sans text-xs font-medium whitespace-nowrap text-bg shadow group-hover:block group-focus-visible:block"
              >
                Pitch corner {i + 1} of 4. Drag to adjust.
              </span>
            </button>
          ))}
          {target && (
            <div className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-1/2" style={pct(target)} aria-hidden="true">
              <span className="absolute inset-0 m-auto size-12 animate-ping rounded-full bg-accent/50 motion-reduce:hidden" />
              <span className="relative grid size-10 place-items-center rounded-full border-2 border-accent bg-accent/25 font-mono text-sm font-bold text-white shadow-[0_0_18px_4px_rgba(200,245,66,0.7)]">
                {next + 1}
              </span>
            </div>
          )}
        </div>
        <p id={`${id}-keys`} className="sr-only">
          Arrow keys move the target, Shift with an arrow key moves it faster, Enter places the point.
        </p>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => onChange(points.slice(0, -1), false)}
            disabled={!points.length}
            className="inline-flex h-9 items-center gap-1.5 rounded-full border border-line px-3 text-sm text-text hover:bg-surface-2 disabled:opacity-40"
          >
            <Undo2 className="size-4" aria-hidden="true" /> Undo
          </button>
          <button
            type="button"
            onClick={() => onChange([], false)}
            disabled={!points.length}
            className="inline-flex h-9 items-center gap-1.5 rounded-full border border-line px-3 text-sm text-text hover:bg-surface-2 disabled:opacity-40"
          >
            <RotateCcw className="size-4" aria-hidden="true" /> Reset
          </button>
          <span className="ml-auto text-sm text-muted">{points.length} of 4 placed</span>
        </div>
        <div className="mt-3 text-sm">
          <button
            type="button"
            onClick={() =>
              onChange(
                [
                  { x: 0, y: 0 },
                  { x: width, y: 0 },
                  { x: width, y: height },
                  { x: 0, y: height },
                ],
                true,
              )
            }
            className="font-medium text-accent-ink underline underline-offset-4 hover:text-text"
          >
            My video already looks straight down on the full pitch
          </button>
          <p className="mt-1 text-xs text-muted">
            {straightDown ? 'Points set to the edges of the frame. ' : ''}Use this only for a straight top-down view.
          </p>
        </div>
      </div>

      <aside className="space-y-4 self-start rounded-xl border border-line bg-bg p-4 text-sm">
        <div className="relative flex items-center gap-2">
          <span className="font-medium text-text">Why do we ask?</span>
          <button
            type="button"
            aria-label="Why do we ask?"
            aria-describedby={`${id}-why`}
            onMouseEnter={() => setWhy(true)}
            onMouseLeave={() => setWhy(false)}
            onFocus={() => setWhy(true)}
            onBlur={() => setWhy(false)}
            onClick={() => setWhy((w) => !w)}
            className="grid size-7 place-items-center rounded-full text-muted hover:bg-surface-2 hover:text-text"
          >
            <Info className="size-4" aria-hidden="true" />
          </button>
          <span
            id={`${id}-why`}
            role="tooltip"
            className={`absolute top-full left-0 z-20 mt-1 w-60 rounded-xl border border-line bg-surface p-3 text-xs leading-relaxed text-text shadow-lg ${why ? 'block' : 'sr-only'}`}
          >
            We use these 4 points to turn your video into a top-down map, so we can measure where players really stand.
          </span>
        </div>
        <StraightenIllustration />
        <p className="text-xs text-muted">Your view → a flat map of the pitch.</p>
      </aside>
    </div>
  )
}
