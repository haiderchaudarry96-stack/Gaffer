import type { ReactNode } from 'react'
import Section from './Section'
import Disclosure from '../ui/Disclosure'
import { LIVE_URL } from '../../lib/links'

const FAQ: { q: string; a: ReactNode }[] = [
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
    a: 'The language model cost $0.021 per synthetic match (195 calls for ten matches, $0.21) and $0.052 for a real 6-minute upload on the demo server (49 calls). The server itself costs about $3.10 a day while it runs, whatever the load. Processing time varies with resolution and server load: a 6-minute 4K clip took 28 minutes, a 30-second sample about 23 seconds. The app reports an estimate from measured frame-processing time after analysis starts.',
  },
  {
    q: 'What about player privacy?',
    a: 'Gaffer works with positions on a pitch, not identities: no face recognition, no names. A video you upload is sent to the demo server on AWS (Sydney) and analysed there. The raw video is deleted 24 hours after its analysis finishes. The results stay on the server: tracked positions, detected events, evidence frames, the report and your approve or reject decisions on uploads. Chat questions are logged as typed, under a random visitor ID, not a name or address. Upload only footage you have the right to share. Footage is used only where its licence allows; the demo data is TeamTrack (MIT licence).',
  },
  {
    q: 'What happens when it is wrong?',
    a: 'Every alert waits for the coach to approve or reject it, and uncertain cases are marked, not alerted. On synthetic test matches it still raised 9 false alerts and missed 6 of 38 real changes, and on real footage it missed Blue’s change at 18:50.',
  },
  {
    q: 'Is it live?',
    a: (
      <>
        Yes. <a href={LIVE_URL} className="font-medium text-accent-ink underline underline-offset-4">{LIVE_URL}</a> runs on AWS: the API, OpenCV and the agent on an EC2 instance behind Caddy (HTTPS), Amazon Bedrock for the agent, S3 for the clips and the model, CloudWatch for the logs. You can replay the recorded match (real TeamTrack drone footage with its stored analysis), analyse one of the two 30-second sample clips, or upload your own top-down clip (up to 6 minutes and 500 MB, one analysis at a time).
      </>
    ),
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
