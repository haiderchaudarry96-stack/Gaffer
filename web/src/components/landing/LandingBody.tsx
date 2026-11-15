import Steps from './Steps'
import DeskStatement from './DeskStatement'
import BeforeAfter from './BeforeAfter'
import Features from './Features'
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
      <Features />
      <BeforeAfter />
      <Limits />
      <Faq />
      <section aria-labelledby="cta-title" className="py-28">
        <Reveal className="mx-auto flex max-w-3xl flex-col items-center px-4 text-center">
          <h2 id="cta-title" className="text-4xl font-bold text-text sm:text-6xl">
            Turn match footage into clearer tactical reviews.
          </h2>
          <p className="mt-5 max-w-xl text-lg text-muted">Explore the analyst desk with a recorded match, or review the footage requirements before uploading your own.</p>
          <ButtonLink to="/app" size="lg" className="mt-8">
            Explore Gaffer
          </ButtonLink>
        </Reveal>
      </section>
      <Footer />
    </div>
  )
}
