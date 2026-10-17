import { useRef, useState } from 'react'
import { m, useMotionValueEvent, useScroll, useTransform } from 'motion/react'
import Nav from '../components/layout/Nav'
import Footer from '../components/layout/Footer'
import Hero from '../components/landing/Hero'
import ProductShot from '../components/landing/ProductShot'
import Steps from '../components/landing/Steps'
import VerifiedStory from '../components/landing/VerifiedStory'
import BeforeAfter from '../components/landing/BeforeAfter'
import Results from '../components/landing/Results'
import Tech from '../components/landing/Tech'
import Limits from '../components/landing/Limits'
import Faq from '../components/landing/Faq'
import Reveal from '../components/ui/Reveal'
import { ButtonLink } from '../components/ui/Button'
import { useLenis } from '../components/landing/useLenis'
import { usePrefersReducedMotion } from '../lib/hooks'

// must match --bg in index.css: :root (dark) and .theme-light
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
  const [light, setLight] = useState(false)
  useMotionValueEvent(scrollYProgress, 'change', (p) => setLight(p > 0.6))

  return (
    <>
      <m.div aria-hidden="true" className="fixed inset-0 -z-50" style={{ backgroundColor: bg }} />
      <Nav light={light} />
      <main id="main">
        <Hero />
        <div className="theme-light">
          <ProductShot ref={firstLight} />
          <Steps />
          <VerifiedStory />
          <BeforeAfter />
          <Results />
          <Tech />
          <Limits />
          <Faq />
          <section aria-labelledby="cta-title" className="py-28">
            <Reveal className="mx-auto flex max-w-3xl flex-col items-center px-4 text-center">
              <h2 id="cta-title" className="text-4xl font-bold text-text sm:text-6xl">
                Watch it check its own eyes.
              </h2>
              <p className="mt-5 text-lg text-muted">Six minutes of real tracked play.</p>
              <ButtonLink to="/app" size="lg" className="mt-8">
                Open the demo
              </ButtonLink>
            </Reveal>
          </section>
        </div>
      </main>
      <div className="theme-light">
        <Footer />
      </div>
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
