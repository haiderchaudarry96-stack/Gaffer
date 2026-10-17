import Reveal from '../ui/Reveal'
import Section from './Section'
import { SmallPrint } from '../ui/Disclosure'

const LIMITS = [
  'Fixed, wide cameras only',
  'No ball, so no possession',
  'Misses some real changes',
  'Tested on one real match',
  'Not live yet',
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
          'All real footage is one match: accuracy numbers come from synthetic matches; real clips give traces and decision tables. Alert suggestions are unchecked model text.',
          'This site replays stored outputs; the backend (EC2, S3, CloudWatch) is being deployed, so chat and report generation are off here.',
        ]}
      />
    </Section>
  )
}
