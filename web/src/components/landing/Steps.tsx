import { m } from 'motion/react'
import { ScanSearch, ShieldCheck, Video } from 'lucide-react'
import Reveal from '../ui/Reveal'
import Section from './Section'

const STEPS = [
  { n: '01', icon: Video, title: 'Upload a match video', line: 'One wide, fixed camera. A drone works best.' },
  { n: '02', icon: ScanSearch, title: 'Follow the team shape', line: 'Review estimated formations on a map beside your footage.' },
  { n: '03', icon: ShieldCheck, title: 'Review the moments that matter', line: 'Check the evidence for a shape change, then approve or reject the alert.' },
]

export default function Steps() {
  return (
    <Section id="how" eyebrow="How it works" title="From match footage to a clearer review." line="Start with a recorded example, or upload a short clip from a fixed camera that sees the whole pitch.">
      <ol className="relative mt-16 grid gap-6 md:grid-cols-3">
        <m.div
          aria-hidden="true"
          className="absolute top-12 right-[16%] left-[16%] hidden h-px origin-left bg-gradient-to-r from-line via-accent-ink/50 to-line md:block"
          initial={{ scaleX: 0 }}
          whileInView={{ scaleX: 1 }}
          viewport={{ once: true, margin: '0px 0px -20% 0px' }}
          transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1], delay: 0.2 }}
        />
        {STEPS.map((s, i) => (
          <li key={s.n}>
            <Reveal delay={i * 0.08} className="h-full">
              <article className="relative flex h-full flex-col rounded-(--radius-card) border border-line bg-surface p-8 transition-transform duration-300 ease-(--ease-out) hover:-translate-y-1">
                <div className="mb-10 flex items-center justify-between">
                  <span className="font-mono text-sm text-muted">{s.n}</span>
                  <span className="relative grid size-12 place-items-center rounded-full border border-line bg-bg text-text">
                    <s.icon className="size-5" aria-hidden="true" />
                  </span>
                </div>
                <h3 className="mb-2 text-2xl font-semibold text-text">{s.title}</h3>
                <p className="text-lg text-muted">{s.line}</p>
              </article>
            </Reveal>
          </li>
        ))}
      </ol>
    </Section>
  )
}
