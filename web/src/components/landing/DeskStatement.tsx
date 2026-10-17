import { ArrowRight } from 'lucide-react'
import Reveal from '../ui/Reveal'
import { ButtonLink } from '../ui/Button'

export default function DeskStatement() {
  return (
    <section aria-labelledby="desk-title" className="pt-8 pb-24 sm:pb-32">
      <Reveal className="mx-auto max-w-3xl px-4 text-center">
        <h2 id="desk-title" className="text-4xl leading-[1.05] font-bold text-text sm:text-6xl">
          One pitch. One timeline. One alert.
        </h2>
        <p className="mt-5 text-lg text-muted sm:text-xl">Everything else waits one click away.</p>
        <ButtonLink to="/app" variant="ghost" size="lg" className="mt-8">
          Open the analyst desk <ArrowRight className="size-4" aria-hidden="true" />
        </ButtonLink>
      </Reveal>
    </section>
  )
}
