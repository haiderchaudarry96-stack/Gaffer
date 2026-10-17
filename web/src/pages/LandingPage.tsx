import { lazy, Suspense, useRef } from 'react'
import { m, useScroll, useTransform } from 'motion/react'
import Nav from '../components/layout/Nav'
import Hero from '../components/landing/Hero'
import ProductShot from '../components/landing/ProductShot'
import { useLenis } from '../components/landing/useLenis'
import { usePrefersReducedMotion } from '../lib/hooks'

// must match --bg in index.css: :root (dark) and .theme-light
// below-the-fold sections load as their own chunk, after the hero
const LandingBody = lazy(() => import('../components/landing/LandingBody'))

const DARK_BG = '#070d0a'
const LIGHT_BG = '#f3f5ef'

/**
 * Landing page. Only the hero is dark; everything below lives in .theme-light (README, decision 2).
 * A fixed backdrop behind the page interpolates dark -> light while the first ~30 % of the first
 * light section scrolls into view (instant under prefers-reduced-motion). Only background-color
 * of one fixed layer changes: no layout work.
 */
export default function LandingPage() {
  useLenis()
  const reduced = usePrefersReducedMotion()
  const firstLight = useRef<HTMLElement>(null)
  const { scrollYProgress } = useScroll({ target: firstLight, offset: ['start end', '0.3 end'] })
  const bg = useTransform(scrollYProgress, (p) => (reduced ? (p < 0.5 ? DARK_BG : LIGHT_BG) : mix(DARK_BG, LIGHT_BG, p)))

  return (
    <>
      <m.div aria-hidden="true" className="fixed inset-0 -z-50" style={{ backgroundColor: bg }} />
      <Nav />
      <main id="main">
        <Hero />
        <div className="theme-light">
          <ProductShot ref={firstLight} />
          <Suspense fallback={<div className="min-h-screen bg-bg" />}>
            <LandingBody />
          </Suspense>
        </div>
      </main>
    </>
  )
}

/** Linear blend of two #rrggbb colours. */
function mix(a: string, b: string, p: number): string {
  const k = Math.min(1, Math.max(0, p))
  const ch = (hex: string, i: number) => parseInt(hex.slice(1 + 2 * i, 3 + 2 * i), 16)
  const out = [0, 1, 2].map((i) => Math.round(ch(a, i) + (ch(b, i) - ch(a, i)) * k))
  return `rgb(${out.join(',')})`
}
