import Nav from '../components/layout/Nav'
import Footer from '../components/layout/Footer'
import Hero from '../components/landing/Hero'
import Steps from '../components/landing/Steps'
import Results from '../components/landing/Results'
import Limits from '../components/landing/Limits'
import Reveal from '../components/ui/Reveal'
import { ButtonLink } from '../components/ui/Button'

export default function LandingPage() {
  return (
    <>
      <Nav />
      <main id="main">
        <Hero />
        <Steps />
        <Results />
        <Limits />
        <section aria-labelledby="cta-title" className="border-t border-line py-24">
          <Reveal className="mx-auto flex max-w-3xl flex-col items-center px-4 text-center">
            <h2 id="cta-title" className="text-4xl font-bold text-text sm:text-5xl">
              Watch it check its own eyes.
            </h2>
            <p className="mt-4 max-w-xl text-muted">
              Open the analyst desk: replay six minutes of real tracked play, see the 16:30 change it confirmed, and the
              step-by-step trace of how it checked.
            </p>
            <ButtonLink to="/app" size="lg" className="mt-8">
              Open the demo
            </ButtonLink>
          </Reveal>
        </section>
      </main>
      <Footer />
    </>
  )
}
