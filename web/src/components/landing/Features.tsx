import { ClipboardCheck, FileText, Map, MessageSquare, ScanSearch, Video } from 'lucide-react'
import Section from './Section'
import Reveal from '../ui/Reveal'

const FEATURES = [
  { icon: Map, title: 'See the whole team', text: 'Keep the match video and tactical map together. Follow where each team is positioned without losing the wider picture.' },
  { icon: ScanSearch, title: 'Find a change in shape', text: 'Use the formation timeline to revisit possible changes. See which moments were checked, confirmed or left uncertain.' },
  { icon: ClipboardCheck, title: 'Keep the final say', text: 'Open the evidence behind an alert and record your response. Optional role advice stays conditional on the available evidence and your setup.' },
  { icon: FileText, title: 'Bring the review together', text: 'Read a match summary alongside the saved analysis and use its cited moments to guide your own discussion.' },
  { icon: MessageSquare, title: 'Ask about the analysis', text: 'In a completed analysis, the analyst answers from stored results when available and flags questions the evidence cannot support.' },
  { icon: Video, title: 'Try it with real footage', text: 'Explore a recorded TeamTrack match, try a short sample or upload suitable footage from your own fixed camera.' },
]

/** Existing capabilities described in terms of the coach's review workflow. */
export default function Features() {
  return (
    <Section id="features" eyebrow="Made for match review" title="More context for your next decision." line="For coaches, analysts and clubs who want to understand team shape and review the evidence themselves.">
      <ul className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {FEATURES.map(({ icon: Icon, title, text }, i) => (
          <li key={title}>
            <Reveal delay={(i % 3) * 0.05} className="h-full">
              <article className="h-full rounded-(--radius-card) border border-line bg-surface p-7 sm:p-8">
                <span className="mb-7 grid size-12 place-items-center rounded-2xl bg-bg text-accent-ink"><Icon className="size-6" aria-hidden="true" /></span>
                <h3 className="text-2xl font-semibold text-text">{title}</h3>
                <p className="mt-3 leading-relaxed text-muted">{text}</p>
              </article>
            </Reveal>
          </li>
        ))}
      </ul>
    </Section>
  )
}
