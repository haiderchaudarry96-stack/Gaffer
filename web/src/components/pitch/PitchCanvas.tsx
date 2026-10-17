import { useEffect, useRef } from 'react'
import type { PlaybackClock } from '../../lib/clock'
import { PositionIndex, type Dot } from './positions'

interface Props {
  index: PositionIndex | null
  pitch: { length_m: number; width_m: number }
  clock: PlaybackClock
  /** "hero": light lines on a transparent background; "mini": a filled pitch panel */
  variant?: 'hero' | 'mini'
  /** faded positions of the last ~1.5 s behind each dot */
  trails?: boolean
  className?: string
  label: string
}

const MARGIN_M = 2.5

function cssVar(name: string, fallback: string) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}

/** Draws IFAB markings for a pitch of the given size (metres). */
function drawMarkings(ctx: CanvasRenderingContext2D, L: number, W: number, s: number) {
  const box = (x: number, y: number, w: number, h: number) => ctx.strokeRect(x * s, y * s, w * s, h * s)
  ctx.beginPath()
  ctx.strokeRect(0, 0, L * s, W * s)
  ctx.moveTo((L / 2) * s, 0)
  ctx.lineTo((L / 2) * s, W * s)
  ctx.stroke()
  ctx.beginPath()
  ctx.arc((L / 2) * s, (W / 2) * s, 9.15 * s, 0, Math.PI * 2)
  ctx.stroke()
  const pa = 40.32
  const ga = 18.32
  box(0, (W - pa) / 2, 16.5, pa)
  box(L - 16.5, (W - pa) / 2, 16.5, pa)
  box(0, (W - ga) / 2, 5.5, ga)
  box(L - 5.5, (W - ga) / 2, 5.5, ga)
  // penalty arcs (outside the box only)
  const ang = Math.acos((16.5 - 11) / 9.15)
  ctx.beginPath()
  ctx.arc(11 * s, (W / 2) * s, 9.15 * s, -ang, ang)
  ctx.stroke()
  ctx.beginPath()
  ctx.arc((L - 11) * s, (W / 2) * s, 9.15 * s, Math.PI - ang, Math.PI + ang)
  ctx.stroke()
  ctx.fillStyle = ctx.strokeStyle
  for (const x of [11, L / 2, L - 11]) {
    ctx.beginPath()
    ctx.arc(x * s, (W / 2) * s, Math.max(1.2, 0.25 * s), 0, Math.PI * 2)
    ctx.fill()
  }
}

/**
 * The 2D top-down pitch with interpolated player dots, drawn on a canvas at display refresh
 * rate. Positions are the real tracked positions from MatchState (metres, origin bottom-left).
 */
export default function PitchCanvas({ index, pitch, clock, variant = 'mini', trails = false, className, label }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const colours = {
      home: cssVar('--team-a', '#ff5b4f'),
      away: cssVar('--team-b', '#44c8ff'),
      referee: cssVar('--muted', '#8fa398'),
      line: variant === 'hero' ? 'rgba(238,244,240,0.34)' : 'rgba(238,244,240,0.30)',
      grass: cssVar('--surface', '#0f1914'),
      stripe: cssVar('--surface-2', '#16231c'),
      bg: cssVar('--bg', '#070d0a'),
    }
    const L = pitch.length_m
    const W = pitch.width_m
    let raf = 0
    let visible = true
    let cssW = 0
    let cssH = 0
    const dots: Dot[] = []
    const trailDots: Dot[] = []

    const resize = () => {
      const rect = canvas.getBoundingClientRect()
      cssW = rect.width
      cssH = rect.height
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = Math.max(1, Math.round(cssW * dpr))
      canvas.height = Math.max(1, Math.round(cssH * dpr))
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }

    const draw = () => {
      const totalL = L + 2 * MARGIN_M
      const totalW = W + 2 * MARGIN_M
      const s = Math.min(cssW / totalL, cssH / totalW)
      const ox = (cssW - totalL * s) / 2 + MARGIN_M * s
      const oy = (cssH - totalW * s) / 2 + MARGIN_M * s
      ctx.clearRect(0, 0, cssW, cssH)
      ctx.save()
      ctx.translate(ox, oy)

      if (variant === 'mini') {
        // mown stripes
        const n = 12
        for (let i = 0; i < n; i++) {
          ctx.fillStyle = i % 2 ? colours.grass : colours.stripe
          ctx.fillRect((i * L * s) / n, 0, (L * s) / n + 0.5, W * s)
        }
      }
      ctx.strokeStyle = colours.line
      ctx.lineWidth = variant === 'hero' ? 1.6 : 1
      drawMarkings(ctx, L, W, s)

      if (index) {
        const t = clock.now()
        // y grows upward in pitch coordinates; canvas y grows downward
        const px = (d: Dot) => d.x * s
        const py = (d: Dot) => (W - d.y) * s
        const r = Math.max(2.6, (variant === 'hero' ? 1.25 : 0.95) * s)
        if (trails) {
          for (const [dt, alpha] of [
            [1.5, 0.08],
            [1.0, 0.14],
            [0.5, 0.22],
          ] as const) {
            index.at(t - dt, trailDots)
            for (const d of trailDots) {
              if (d.team === 'referee' || d.team === 'unknown') continue
              ctx.globalAlpha = alpha
              ctx.fillStyle = colours[d.team]
              ctx.beginPath()
              ctx.arc(px(d), py(d), r * 0.8, 0, Math.PI * 2)
              ctx.fill()
            }
          }
          ctx.globalAlpha = 1
        }
        index.at(t, dots)
        for (const d of dots) {
          if (d.team === 'unknown') {
            // seen by OpenCV, team not decided yet: a hollow ring, no team colour
            ctx.strokeStyle = colours.referee
            ctx.lineWidth = 1.25
            ctx.beginPath()
            ctx.arc(px(d), py(d), r * 0.8, 0, Math.PI * 2)
            ctx.stroke()
            continue
          }
          const c = colours[d.team]
          ctx.fillStyle = c
          ctx.beginPath()
          ctx.arc(px(d), py(d), d.team === 'referee' ? r * 0.6 : r, 0, Math.PI * 2)
          ctx.fill()
          if (d.goalkeeper && d.team !== 'referee') {
            ctx.strokeStyle = colours.bg
            ctx.lineWidth = Math.max(1, r * 0.35)
            ctx.beginPath()
            ctx.arc(px(d), py(d), r * 0.45, 0, Math.PI * 2)
            ctx.stroke()
          }
        }
      }
      ctx.restore()
    }

    const loop = () => {
      if (visible) draw()
      raf = requestAnimationFrame(loop)
    }

    resize()
    draw()
    const ro = new ResizeObserver(() => {
      resize()
      draw()
    })
    ro.observe(canvas)
    const io = new IntersectionObserver(([e]) => {
      visible = e.isIntersecting
    })
    io.observe(canvas)
    raf = requestAnimationFrame(loop)
    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
      io.disconnect()
    }
  }, [index, pitch.length_m, pitch.width_m, clock, variant, trails])

  return <canvas ref={canvasRef} className={className} role="img" aria-label={label} />
}
