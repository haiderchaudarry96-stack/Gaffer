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
      <Footer />
    </div>
  )
}
