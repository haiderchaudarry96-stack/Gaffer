import Section from './Section'
import Disclosure from '../ui/Disclosure'

const FAQ = [
  {
    q: 'What footage works?',
    a: 'One fixed, wide camera that sees the whole pitch. It is tested on TeamTrack drone footage (one match, filmed from above). A fixed side camera works experimentally and is never alerted. Gaffer samples 2–4 frames per second.',
  },
  {
    q: 'Why only drone or fixed cameras?',
    a: 'Positions in metres come from a homography fitted to the pitch lines, which needs a camera that does not move. Before every second look, an OpenCV camera check measures pan, zoom and cuts and refuses the window if the camera moved (limits: 25 px/s, 3 % zoom).',
  },
  {
    q: 'What does the AI decide, and what do the rules decide?',
    a: 'Fixed rules in code give every verdict: does the new shape hold, does it revert, is the camera usable. Nova 2 Lite on Amazon Bedrock chooses the calls (which window, which frame rate) and writes the explanation, which code then checks. On 68 synthetic candidates its decisions matched the rules-only run 68 / 68.',
  },
  {
    q: 'What does a match cost?',
    a: 'The language model cost $0.021 per synthetic match (195 calls for ten matches, $0.21). Vision runs on a laptop CPU today: about 1.2–1.4 s per second of drone video, and 2–4 minutes per second look. Cloud hosting costs are not measured yet.',
  },
  {
    q: 'What about player privacy?',
    a: 'Gaffer works with positions on a pitch, not identities: no face recognition, no names. In this demo, a video you load stays in your browser. Footage is used only where its licence allows; the demo data is TeamTrack (MIT licence).',
  },
  {
    q: 'What happens when it is wrong?',
    a: 'Every alert waits for the coach to approve or reject it, and uncertain cases are marked, not alerted. On synthetic test matches it still raised 9 false alerts and missed 6 of 38 real changes, and on real footage it missed Blue’s change at 18:50.',
  },
  {
    q: 'Is it live?',
    a: 'Not yet. This site replays stored outputs from one real match. The backend that runs OpenCV and the agent on AWS is being deployed.',
  },
  {
    q: 'What data was it tested on?',
    a: 'Synthetic 90-minute matches with exact ground truth (the official numbers: seeds 110–119) and the TeamTrack soccer dataset (Scott et al., 2024, MIT licence): drone and side cameras of one match.',
  },
]

export default function Faq() {
  return (
    <Section id="faq" eyebrow="FAQ" title="Questions coaches ask.">
      <ul className="mt-12 max-w-4xl divide-y divide-line border-y border-line">
        {FAQ.map((f) => (
          <li key={f.q}>
            <Disclosure summary={<span className="text-xl font-semibold text-text">{f.q}</span>} summaryClassName="py-6 text-text">
              <p className="pb-6 text-lg leading-relaxed text-muted">{f.a}</p>
            </Disclosure>
          </li>
        ))}
      </ul>
    </Section>
  )
}
