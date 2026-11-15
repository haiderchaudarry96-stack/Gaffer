import { Camera, Film, UserCheck } from 'lucide-react'
import Section from './Section'

const GUIDE = [
  { icon: Camera, title: 'A clear view of the pitch', text: 'Choose a fixed, elevated view with both teams in frame and clearly different kits.' },
  { icon: Film, title: 'Recorded footage, at your pace', text: 'Upload a short recording or explore the example match. There is no live camera connection.' },
  { icon: UserCheck, title: 'Your experience stays central', text: 'Treat shape estimates and advice as review aids. Check uncertain moments against the video.' },
]

export default function Limits() {
  return (
    <Section id="footage" eyebrow="Before you start" title="Built for the right footage.">
      <ul className="mt-12 grid gap-8 md:grid-cols-3">
        {GUIDE.map(({ icon: Icon, title, text }) => (
          <li key={title} className="border-t border-line pt-6">
            <Icon className="mb-5 size-6 text-accent-ink" aria-hidden="true" />
            <h3 className="text-xl font-semibold text-text">{title}</h3>
            <p className="mt-3 leading-relaxed text-muted">{text}</p>
          </li>
        ))}
      </ul>
    </Section>
  )
}
