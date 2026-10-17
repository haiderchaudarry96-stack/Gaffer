import { motion } from 'motion/react'
import { ScanSearch, ShieldCheck, Video } from 'lucide-react'
import Reveal from '../ui/Reveal'

const STEPS = [
  {
    n: '01',
    icon: Video,
    title: 'Upload a match video',
    body: 'One wide, fixed camera is enough: a drone above the pitch works best today. Gaffer samples it at 2–4 frames per second, plenty to read a team’s shape.',
    detail: 'Tested on TeamTrack drone footage (one match).',
  },
  {
    n: '02',
    icon: ScanSearch,
    title: 'OpenCV maps every player onto the pitch',
    body: 'OpenCV 5 finds the players, tracks them, splits the teams by shirt colour with cv2.kmeans, and turns pixels into metres with a homography fitted to the pitch lines.',
    detail: 'Drone view: 0.17 m position error, team colour right 98.6 % of the time.',
  },
  {
    n: '03',
    icon: ShieldCheck,
    title: 'The agent double-checks, then alerts the coach',
    body: 'Every possible shape change gets a camera check and a second OpenCV look at a higher frame rate. Fixed rules give the verdict. Only confirmed changes reach you, with an evidence image, and they wait for your approve or reject.',
    detail: 'Rules decide; Nova 2 Lite on Bedrock runs the checks and words the explanation.',
  },
]

export default function Steps() {
  return (
    <section id="how" aria-labelledby="how-title" className="relative scroll-mt-20 py-24 sm:py-32">
      <div className="pitch-pattern absolute inset-0 -z-10 opacity-40" aria-hidden="true" />
      <div className="mx-auto max-w-7xl px-4 sm:px-6">
        <Reveal>
          <p className="mb-3 font-mono text-xs tracking-widest text-accent uppercase">How it works</p>
          <h2 id="how-title" className="max-w-2xl text-4xl font-bold text-text sm:text-5xl">
            Three steps from video to a verified alert.
          </h2>
        </Reveal>

        <ol className="relative mt-16 grid gap-6 md:grid-cols-3">
          {/* the line that connects the steps, drawn on scroll */}
          <motion.div
            aria-hidden="true"
            className="absolute top-[3.25rem] right-[16%] left-[16%] hidden h-px origin-left bg-gradient-to-r from-line via-accent/60 to-line md:block"
            initial={{ scaleX: 0 }}
            whileInView={{ scaleX: 1 }}
            viewport={{ once: true, margin: '0px 0px -20% 0px' }}
            transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1], delay: 0.2 }}
          />
          {STEPS.map((s, i) => (
            <li key={s.n}>
              <Reveal delay={i * 0.08} className="h-full">
                <article className="relative flex h-full flex-col rounded-(--radius-card) border border-line bg-surface p-7 transition-transform duration-300 ease-(--ease-out) hover:-translate-y-1">
                  <div className="mb-8 flex items-center justify-between">
                    <span className="font-mono text-sm text-muted">{s.n}</span>
                    <span className="relative grid size-12 place-items-center rounded-full border border-line bg-bg text-text">
                      <s.icon className="size-5" aria-hidden="true" />
                    </span>
                  </div>
                  <h3 className="mb-3 text-2xl font-semibold text-text">{s.title}</h3>
                  <p className="text-[15px] leading-relaxed text-muted">{s.body}</p>
                  <p className="mt-auto border-t border-line pt-4 text-xs leading-relaxed text-muted">
                    <span className="sr-only">Measured: </span>
                    {s.detail}
                  </p>
                </article>
              </Reveal>
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}
