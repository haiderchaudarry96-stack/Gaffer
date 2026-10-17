import { useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, m, useInView } from 'motion/react'
import PitchCanvas from '../pitch/PitchCanvas'
import Reveal from '../ui/Reveal'
import { SmallPrint } from '../ui/Disclosure'
import { PlaybackClock } from '../../lib/clock'
import { getRunRows, getTrace, usePositions } from '../../lib/matchData'
import { STORY_EVENT } from '../../lib/windows'
import { useResource } from '../../data/useResource'
import { traceForEvent, type TraceToolCall } from '../../data'
import { sampleUrl } from '../../data/source'

interface Beat {
  clock: string
  title: string
  big: string
  label: string
  t: number
  image?: boolean
}

const pct = (v: unknown) => (typeof v === 'number' ? `${Math.round(v * 100)} %` : '—')

/** The four beats of the real evt_003 trace, read from trace_llm.jsonl and report_llm.json. */
function useBeats(): Beat[] | null {
  const trace = useResource(getTrace, 'trace')
  const rows = useResource(getRunRows, 'run_rows')
  return useMemo(() => {
    if (trace.status !== 'ready' || rows.status !== 'ready') return null
    const steps = traceForEvent(trace.data, STORY_EVENT)
    const tool = (name: string) => steps.find((s): s is TraceToolCall => s.kind === 'tool_call' && s.tool === name)
    const row = rows.data.find((r) => r.event_id === STORY_EVENT)
    const q = tool('check_frame_quality')?.result_summary
    const r = tool('reanalyse_window')?.result_summary
    const vs = (r?.vs_event ?? {}) as Record<string, unknown>
    if (!row || !q || !r) return null
    return [
      { clock: row.clock, title: 'Something changed', big: `${row.from} → ${row.to}`, label: `White, first pass. Only ${pct(row.first_pass.coverage_before)} of frames before it show enough players.`, t: 985 },
      { clock: 'OpenCV', title: 'Is the camera usable?', big: pct(q.homography_ok_share), label: `pitch lines fit · camera moved ${q.camera_shift_px_per_s_max} px/s`, t: 1000 },
      { clock: 'OpenCV', title: 'Look again, closer', big: pct(vs.after_share_new), label: `of ${vs.confident_after} clear readings in 3-4-3 at ${r.sample_fps} fps`, t: 1010 },
      { clock: 'You', title: 'Verified. Your call.', big: 'Pending', label: 'Alert with evidence, waiting for approve or reject.', t: 1005, image: true },
    ]
  }, [trace, rows])
}

function BeatText({ beat, i, onActive }: { beat: Beat; i: number; onActive: (i: number) => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const inView = useInView(ref, { amount: 0.6 })
  useEffect(() => {
    if (inView) onActive(i)
  }, [inView, i, onActive])
  return (
    <div ref={ref} className="flex min-h-[70vh] flex-col justify-center py-10 lg:py-0">
      <p className="font-mono text-sm text-accent-ink">
        0{i + 1} · {beat.clock}
      </p>
      <h3 className="mt-3 text-3xl font-bold text-text sm:text-5xl">{beat.title}</h3>
      {/* on small screens the number sits with the text; the sticky panel is desktop only */}
      <p className="mt-4 font-mono text-4xl font-semibold text-text lg:hidden">{beat.big}</p>
      <p className="mt-3 max-w-md text-lg text-muted">{beat.label}</p>
    </div>
  )
}

export default function VerifiedStory() {
  const beats = useBeats()
  const [active, setActive] = useState(0)
  const { index } = usePositions()
  const clock = useMemo(() => new PlaybackClock({ min: 900, max: 1259.5, start: 985 }), [])
  const beat = beats?.[active]
  useEffect(() => {
    if (beat) clock.seek(beat.t)
  }, [beat, clock])

  return (
    <section id="verified" aria-labelledby="verified-title" className="scroll-mt-20 py-24 sm:py-32">
      <div className="mx-auto max-w-7xl px-4 sm:px-6">
        <Reveal>
          <p className="mb-4 font-mono text-xs tracking-widest text-accent-ink uppercase">Verified, not guessed</p>
          <h2 id="verified-title" className="max-w-4xl text-4xl leading-[1.05] font-bold text-text sm:text-6xl">
            It looks twice before it tells you.
          </h2>
          <p className="mt-5 max-w-2xl text-lg text-muted sm:text-xl">The real 16:30 alert, step by step.</p>
        </Reveal>

        <div className="mt-10 grid gap-10 lg:grid-cols-2">
          <div className="hidden lg:block">
            <div className="sticky top-[15vh] h-[70vh]">
              <div className="flex h-full flex-col justify-center gap-6 rounded-(--radius-card) border border-line bg-surface p-8">
                <AnimatePresence mode="wait">
                  {beat && (
                    <m.div
                      key={active}
                      initial={{ opacity: 0, y: 16 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -16 }}
                      transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
                    >
                      <p className="font-mono text-6xl font-semibold tracking-tight text-text xl:text-7xl">{beat.big}</p>
                      <p className="mt-2 text-muted">{beat.title}</p>
                    </m.div>
                  )}
                </AnimatePresence>
                <div className="relative aspect-[110/73] w-full overflow-hidden rounded-xl">
                  {beat?.image ? (
                    <img
                      src={sampleUrl('w900_1260/evt_003.jpg')}
                      alt="Evidence for the 16:30 alert: White's players on a drone frame with their 3-4-3 lines, and the average shapes before and after."
                      className="size-full object-cover object-top"
                      loading="lazy"
                    />
                  ) : (
                    <PitchCanvas
                      index={index}
                      pitch={{ length_m: 105, width_m: 68 }}
                      clock={clock}
                      variant="mini"
                      className="size-full"
                      label={`Tracked positions at ${beat ? beat.clock : '16:25'}`}
                    />
                  )}
                </div>
                <ol className="flex gap-2" aria-label="Story progress">
                  {(beats ?? []).map((_, i) => (
                    <li key={i} className={`h-1 flex-1 rounded-full transition-colors ${i <= active ? 'bg-accent-ink' : 'bg-surface-2'}`}>
                      <span className="sr-only">
                        Step {i + 1}
                        {i === active ? ' (current)' : ''}
                      </span>
                    </li>
                  ))}
                </ol>
              </div>
            </div>
          </div>
          <div>{beats?.map((b, i) => <BeatText key={i} beat={b} i={i} onActive={setActive} />)}</div>
        </div>
        <SmallPrint
          items={[
            'Honest reading: the first pass alone would also have confirmed (85 % of 13 readings). Here OpenCV set the path (camera check, second look at 6 fps) and produced the evidence; it did not change the decision. On real footage a verdict flipped only on a simulated camera pan.',
            'This window (15:00–21:00) was chosen with ground-truth positions because the half’s two lasting changes happen in it: a demonstration, not a sample. The other lasting change, Blue at 18:50, was missed by the return-leg rule.',
            'The second look re-ran OpenCV on 840 frames; on the laptop CPU that took 252 s (cached in this run). The camera check took 11.3 s.',
            'Rules decide the verdict; Nova 2 Lite chose the calls and wrote the explanation, which code then checked.',
          ]}
        />
      </div>
    </section>
  )
}
