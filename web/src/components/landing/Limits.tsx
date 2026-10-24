import Reveal from '../ui/Reveal'
import Section from './Section'
import { SmallPrint } from '../ui/Disclosure'

const LIMITS = [
  'Fixed, wide cameras only',
  'No ball, so no possession',
  'Misses some real changes',
  'Tested on one real match',
  'Long clips take a while (a 6 min clip took 28 min on the demo server)',
]

export default function Limits() {
  return (
    <Section id="limits" eyebrow="Honest limits" title="What it can’t do yet." line="An analyst that admits doubt beats one that bluffs.">
      <ul className="mt-12 flex flex-wrap gap-3">
        {LIMITS.map((l, i) => (
          <li key={l}>
            <Reveal delay={i * 0.05}>
              <span className="inline-flex rounded-full border border-line bg-surface px-5 py-3 text-lg text-text">{l}</span>
            </Reveal>
          </li>
        ))}
      </ul>
      <SmallPrint
        items={[
          'On real drone footage, OpenCV results changed the agent’s next step (a second look at 6 fps, second looks skipped) but never the final verdict; the one verdict an OpenCV check flipped used real frames with simulated camera motion.',
          'The one confirmed real alert (16:30) is in a window chosen with ground-truth positions: a demonstration, not a sample.',
          'Blue’s switch to 4-2-3-1 at 18:50 held for 220 s but the return-leg rule rejected it; the tested fix added 25 false alerts on synthetic data, so it stays off.',
          'Panning and zooming cameras are refused by the camera check. The fixed side-camera view is experimental and never alerted.',
          'The drone pipeline does not detect the ball, so shapes come from player positions only and set pieces are not recognised as such.',
          'All real footage is one match: accuracy numbers come from synthetic matches; real clips give traces and decision tables. Alert suggestions are checked against the formation change and replaced by a code template when wrong; they are never part of the decision.',
          'The recorded match shows outputs stored from an earlier analysis. Your own upload and the two sample clips are analysed on the AWS server, one analysis at a time (the others wait their turn). A 6 min 4K upload took 28 min (OpenCV detection 403 s, the agent’s second looks the rest); a 30 s sample takes about 23 s. Chat and the agent’s Bedrock calls stop for the day at 300 calls or $1.00 across all visitors; the rules still run.',
        ]}
      />
    </Section>
  )
}
