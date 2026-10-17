import { CircleSlash } from 'lucide-react'
import Reveal from '../ui/Reveal'

const LIMITS = [
  {
    title: 'A flipped verdict on real footage — only on a simulated pan',
    body: 'On real drone footage, OpenCV results changed the agent’s next step (a second look at 6 fps, second looks skipped), but never the final verdict. The one verdict an OpenCV check flipped used real frames with simulated camera motion.',
  },
  {
    title: 'One confirmed real alert, in a hand-picked window',
    body: 'The confirmed 16:30 change in the demo sits in a window chosen with ground-truth positions because the half’s lasting changes happen there. It is a demonstration, not a sample.',
  },
  {
    title: 'It misses some real changes',
    body: 'Blue’s switch to 4-2-3-1 at 18:50 held for 220 s, but the return-leg rule rejected it. The tested fix added 25 false alerts on synthetic data, so it stays off.',
  },
  {
    title: 'Fixed, wide cameras only',
    body: 'Panning and zooming cameras are not supported: the camera check refuses them. The fixed side-camera view is experimental and is never alerted.',
  },
  {
    title: 'No ball, so no possession or pressing',
    body: 'The drone pipeline does not detect the ball, so shapes are read from player positions alone and set pieces are not recognised as such.',
  },
  {
    title: 'Small real-world test',
    body: 'All real footage is one match. Accuracy numbers come from synthetic matches; real clips give traces and decision tables. Alert suggestions are still unchecked model text.',
  },
  {
    title: 'Not live yet',
    body: 'This demo replays stored outputs. The cloud backend (EC2, S3, CloudWatch) is still being built, so chat and report generation are switched off here.',
  },
]

export default function Limits() {
  return (
    <section id="limits" aria-labelledby="limits-title" className="scroll-mt-20 border-t border-line py-24 sm:py-32">
      <div className="mx-auto max-w-7xl px-4 sm:px-6">
        <Reveal>
          <p className="mb-3 font-mono text-xs tracking-widest text-warn uppercase">Honest limits</p>
          <h2 id="limits-title" className="max-w-2xl text-4xl font-bold text-text sm:text-5xl">
            What it can’t do yet.
          </h2>
          <p className="mt-4 max-w-2xl text-muted">
            An analyst that admits uncertainty beats one that bluffs. These are the known gaps, from our own failure log.
          </p>
        </Reveal>
        <ul className="mt-12 grid gap-4 md:grid-cols-2">
          {LIMITS.map((l, i) => (
            <li key={l.title}>
              <Reveal delay={(i % 2) * 0.07} className="h-full">
                <div className="flex h-full gap-4 rounded-(--radius-card) border border-line bg-surface p-6">
                  <CircleSlash className="mt-0.5 size-5 shrink-0 text-warn" aria-hidden="true" />
                  <div>
                    <h3 className="mb-1.5 font-sans text-base font-semibold tracking-normal text-text">{l.title}</h3>
                    <p className="text-sm leading-relaxed text-muted">{l.body}</p>
                  </div>
                </div>
              </Reveal>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
