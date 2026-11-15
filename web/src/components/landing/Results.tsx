import Reveal from '../ui/Reveal'
import Section from './Section'
import CountUp from './CountUp'
import { SmallPrint } from '../ui/Disclosure'

const STATS = [
  { before: '34 →', value: 9, label: 'false alerts', scope: 'synthetic evaluation' },
  { value: 97.7, decimals: 1, suffix: '%', label: 'formation windows correct', scope: 'synthetic evaluation' },
  { value: 0.91, decimals: 2, label: 'player detection F1', scope: 'TeamTrack drone clips' },
  { value: 98.6, decimals: 1, suffix: '%', label: 'team labels correct', scope: 'TeamTrack drone clips' },
]

/** Every number is from CLAUDE.md "Key numbers" / AGENT_DESIGN §14; all caveats are in the small print. */
export default function Results() {
  return (
    <Section id="results" eyebrow="Evaluation" title="Measured results, with the limits in view." line="Synthetic matches and real footage answer different questions, so we report them separately.">
      <div className="mt-16 grid gap-x-8 gap-y-12 sm:grid-cols-2 lg:grid-cols-4">
        {STATS.map((s, i) => (
          <Reveal key={s.label} delay={i * 0.07}>
            <p className="font-mono text-6xl font-semibold tracking-tight text-text sm:text-7xl">
              {s.before && <span className="mr-2 text-3xl text-muted">{s.before}</span>}
              <CountUp value={s.value} decimals={s.decimals} suffix={s.suffix} />
            </p>
            <p className="mt-3 border-t border-line pt-3 text-lg text-muted">{s.label}</p>
            <p className="mt-1 text-xs text-muted">{s.scope}</p>
          </Reveal>
        ))}
      </div>
      <SmallPrint
        items={[
          'False alerts 34 → 9 and real changes alerted 34 / 38 → 32 / 38: synthetic matches, seeds 110–119, run once with frozen rules on 17 Oct. The agent never ran on these seeds before, but the tactics engine’s output on them had been seen: agent-untouched, not unseen. This is a synthetic evaluation, not a customer match result.',
          '97.7 % of 30 s windows have the right formation when the engine is confident (confident on 79.3 %), synthetic seeds 110–119. The generator and the engine share one model of a formation, so this is an upper bound.',
          'Detection F1 0.912 within 1 m (precision 0.858, recall 0.974) on the TeamTrack drone eval clips from one match. Most precision misses are referees and staff, which the ground truth does not label. Side view: 0.78 within 2 m. These clips are not a held-out customer deployment.',
          'Team colour right for 98.6 % of players on the drone eval clips at 4 fps tracking; 2.4 % left “unknown”. Side view: 92.1 %.',
          'Who decides: fixed rules give every verdict. Nova 2 Lite on Amazon Bedrock picks the calls and writes the explanation; its decisions matched the rules-only run on 68 / 68 synthetic candidates, so the LLM adds nothing to the decisions.',
          'Processing time varies with video resolution, server hardware and load. The app reports an estimate from measured frame-processing time once analysis starts.',
        ]}
      />
    </Section>
  )
}
