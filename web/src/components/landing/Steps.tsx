import { m } from 'motion/react'
import { ScanSearch, ShieldCheck, Video } from 'lucide-react'
import Reveal from '../ui/Reveal'
import Section from './Section'
import { SmallPrint } from '../ui/Disclosure'

const STEPS = [
  { n: '01', icon: Video, title: 'Upload a match video', line: 'One wide, fixed camera. A drone works best.' },
  { n: '02', icon: ScanSearch, title: 'OpenCV maps every player', line: 'Pixels become metres on the pitch.' },
  { n: '03', icon: ShieldCheck, title: 'It checks, then alerts you', line: 'A second look before it says a word.' },
]

export default function Steps() {
  return (
    <Section id="how" eyebrow="How it works" title="Video in. Verified alert out.">
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
      <SmallPrint
        items={[
          'Tested on one TeamTrack drone match; a fixed side camera is experimental and never alerted. Gaffer samples the video at 2–4 frames per second.',
          'OpenCV 5 finds and tracks the players, splits the teams by shirt colour (cv2.kmeans) and maps pixels to metres with a homography fitted to the pitch lines. Drone view: 0.17 m position error, team right 98.6 % of the time.',
          'Each possible shape change gets an OpenCV camera check and a second OpenCV look at a higher frame rate. Fixed rules give the verdict; Nova 2 Lite on Amazon Bedrock runs the checks and words the explanation. Confirmed changes wait for the coach to approve or reject.',
        ]}
      />
    </Section>
  )
}
