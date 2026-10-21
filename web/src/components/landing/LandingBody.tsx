import Steps from './Steps'
import DeskStatement from './DeskStatement'
import VerifiedStory from './VerifiedStory'
import BeforeAfter from './BeforeAfter'
import Results from './Results'
import Tech from './Tech'
import Limits from './Limits'
import Faq from './Faq'
import Footer from '../layout/Footer'
import Reveal from '../ui/Reveal'
import Disclosure from '../ui/Disclosure'
import { ButtonLink } from '../ui/Button'

/**
 * Everything below the product shot. It has its own light background (so contrast never depends
 * on the scroll-linked backdrop) and loads as a separate chunk after the hero.
 */
export default function LandingBody() {
  return (
    <div className="bg-bg">
      <DeskStatement />
      <Steps />
      <VerifiedStory />
      <BeforeAfter />
      <section id="judges" aria-labelledby="judges-title" className="scroll-mt-20 py-12 sm:py-16">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <Reveal>
            <p className="mb-3 font-mono text-xs tracking-widest text-accent-ink uppercase">For judges and technical readers</p>
            <h2 id="judges-title" className="max-w-4xl text-3xl leading-tight font-bold text-text sm:text-4xl">
              Evidence, results, and how the system works
            </h2>
            <p className="mt-3 max-w-2xl text-muted">
              Open the brief for evaluation figures, their limits, OpenCV&apos;s role, and what Amazon Bedrock does.
            </p>
          </Reveal>
          <Disclosure
            className="mt-8 border-y border-line py-4"
            title="Open judge and technical details"
            summaryClassName="rounded-lg py-3 text-left text-base font-semibold text-text hover:text-accent-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-ink"
            summary={<span>Open judge and technical details</span>}
          >
            <div className="-mx-4 sm:-mx-6">
              <Results />
              <Tech />
            </div>
          </Disclosure>
        </div>
      </section>
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
      <Footer />
    </div>
  )
}
