import Reveal from '../ui/Reveal'
import CountUp from './CountUp'

interface Stat {
  value: number
  decimals?: number
  suffix?: string
  before?: string
  label: string
  caveat: string
}

/** Every number here is copied from CLAUDE.md "Key numbers" / AGENT_DESIGN.md §14, caveats included. */
const STATS: Stat[] = [
  {
    before: '34 →',
    value: 9,
    label: 'false alerts, alert-on-everything vs Gaffer’s checks',
    caveat:
      'Synthetic matches (seeds 110–119), run once with frozen rules. Real changes alerted: 34 / 38 → 32 / 38. The agent never ran on these seeds before, but the tactics engine’s output on them had been seen: untouched by the agent, not unseen.',
  },
  {
    value: 97.7,
    decimals: 1,
    suffix: ' %',
    label: 'formation right per 30 s window, when confident',
    caveat:
      'Synthetic seeds 110–119; confident on 79.3 % of windows. The generator and the engine share one model of a formation, so this is an upper bound.',
  },
  {
    value: 0.912,
    decimals: 3,
    label: 'player detection F1 within 1 m, drone view',
    caveat:
      'Precision 0.858 / recall 0.974 on the TeamTrack drone eval clips (one match). Most misses on precision are referees and staff, which the ground truth does not label. Side view: 0.78 within 2 m.',
  },
  {
    value: 98.6,
    decimals: 1,
    suffix: ' %',
    label: 'players put in the right team, drone view',
    caveat: 'TeamTrack drone eval clips at 4 fps tracking; 2.4 % of players left “unknown”. Side view: 92.1 %.',
  },
]

export default function Results() {
  return (
    <section id="results" aria-labelledby="results-title" className="scroll-mt-20 border-t border-line py-24 sm:py-32">
      <div className="mx-auto max-w-7xl px-4 sm:px-6">
        <Reveal>
          <p className="mb-3 font-mono text-xs tracking-widest text-accent uppercase">Results</p>
          <h2 id="results-title" className="max-w-2xl text-4xl font-bold text-text sm:text-5xl">
            Measured, with the small print attached.
          </h2>
        </Reveal>
        <div className="mt-14 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {STATS.map((s, i) => (
            <Reveal key={s.label} delay={i * 0.07} className="h-full">
              <figure className="flex h-full flex-col rounded-(--radius-card) border border-line bg-surface p-6">
                <div className="font-mono text-5xl font-semibold tracking-tight text-text">
                  {s.before && <span className="mr-2 text-3xl text-muted">{s.before}</span>}
                  <CountUp value={s.value} decimals={s.decimals} suffix={s.suffix} />
                </div>
                <figcaption className="mt-3 flex flex-1 flex-col">
                  <span className="font-medium text-text">{s.label}</span>
                  <span className="mt-4 border-t border-line pt-4 text-xs leading-relaxed text-muted">{s.caveat}</span>
                </figcaption>
              </figure>
            </Reveal>
          ))}
        </div>
        <Reveal>
          <div className="mt-6 grid gap-5 lg:grid-cols-2">
            <p className="rounded-(--radius-card) border border-line bg-surface p-6 text-sm leading-relaxed text-muted">
              <span className="font-semibold text-text">Who decides.</span> Fixed rules give every verdict. Amazon Nova 2
              Lite on Bedrock orchestrates the checks and writes the explanation; on the 68 synthetic candidates its
              decisions matched the rules-only run 68 / 68, so <span className="text-text">the LLM adds nothing to the
              decisions</span>. LLM cost: $0.021 per synthetic match.
            </p>
            <p className="rounded-(--radius-card) border border-line bg-surface p-6 text-sm leading-relaxed text-muted">
              <span className="font-semibold text-text">Speed.</span> Drone view, laptop CPU, no GPU: about 1.2–1.4 s of
              processing per second of video with 4 fps tracking. A second look at a 145 s window at 4 fps took 171.6 s;
              the camera check takes 8–13 s.
            </p>
          </div>
        </Reveal>
      </div>
    </section>
  )
}
