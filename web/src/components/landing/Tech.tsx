import Reveal from '../ui/Reveal'
import Section from './Section'
import { SmallPrint } from '../ui/Disclosure'

const OPENCV = [
  { api: 'cv2.dnn', what: 'Runs the YOLOX-S detector on the side camera.', fact: 'F1 0.78 within 2 m' },
  { api: 'cv2.kmeans', what: 'Splits the players into teams by shirt colour.', fact: '98.6 % right, drone view' },
  { api: 'cv2.findHomography', what: 'Maps pixels to metres from the pitch lines.', fact: '0.11 m mean error' },
  { api: 'cv2.findTransformECC', what: 'Re-anchors the wobbling drone every frame.', fact: '0.198 → 0.040 m drift' },
  { api: 'ORB + estimateAffinePartial2D', what: 'Refuses panning or zooming cameras.', fact: '8–13 s per check' },
  { api: 'Evidence rendering', what: 'Draws the new shape onto the real frame.', fact: '1280 px JPEG, ≤ 1 MB' },
]

const AWS = [
  { name: 'Amazon Bedrock · Nova 2 Lite', what: 'Runs the checks and words each explanation. Called with the instance’s IAM role, no keys.', status: 'in use' },
  { name: 'Amazon EC2', what: 'Runs the API, OpenCV and the agent behind Caddy HTTPS, in Sydney.', status: 'in use' },
  { name: 'Amazon S3', what: 'Holds the replay clips, the two sample clips and the detector model.', status: 'in use' },
  { name: 'Amazon CloudWatch', what: 'Receives the server logs and two usage metrics.', status: 'in use' },
]

export default function Tech() {
  return (
    <Section id="tech" eyebrow="Built with" title="OpenCV 5 does the seeing." line="Amazon Bedrock does the talking.">
      <h3 className="mt-16 mb-6 font-sans text-sm font-semibold tracking-wide text-muted uppercase">Where OpenCV 5 is used</h3>
      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {OPENCV.map((c, i) => (
          <li key={c.api}>
            <Reveal delay={(i % 3) * 0.06} className="h-full">
              <div className="flex h-full flex-col rounded-(--radius-card) border border-line bg-surface p-6 transition-transform duration-300 ease-(--ease-out) hover:-translate-y-1">
                <p className="font-mono text-sm font-semibold text-text">{c.api}</p>
                <p className="mt-2 text-muted">{c.what}</p>
                <p className="mt-auto pt-5 font-mono text-2xl font-semibold text-text">{c.fact}</p>
              </div>
            </Reveal>
          </li>
        ))}
      </ul>
      <h3 className="mt-14 mb-6 font-sans text-sm font-semibold tracking-wide text-muted uppercase">Where AWS is used</h3>
      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {AWS.map((c, i) => (
          <li key={c.name}>
            <Reveal delay={i * 0.06} className="h-full">
              <div className="flex h-full flex-col rounded-(--radius-card) border border-line bg-surface p-6">
                <span className="self-start rounded-full border border-accent-ink/40 px-2.5 py-0.5 font-mono text-[11px] font-semibold text-accent-ink uppercase">
                  {c.status}
                </span>
                <p className="mt-4 font-semibold text-text">{c.name}</p>
                <p className="mt-1 text-muted">{c.what}</p>
              </div>
            </Reveal>
          </li>
        ))}
      </ul>
      <SmallPrint
        items={[
          'Detection: the drone view uses a classical OpenCV detector (F1 0.912 within 1 m); tiled YOLOX-S through cv2.dnn found too few players from above (recall 0.06) and runs on the side camera only (3.4 s per frame on the laptop CPU).',
          'Homography: one per view, fitted to 31 pitch landmarks on the drone view; 0.11 m mean / 0.38 m max held-out landmark error. Side view: two sectioned homographies, 0.53 m mean.',
          'Drift: median line error 0.198 m uncorrected, 0.089 m anchored once per clip, 0.040 m anchored every frame (142 ms per frame).',
          'Camera check: ORB features and cv2.estimateAffinePartial2D on frame pairs 0.5 s apart, plus HSV-histogram cut detection; limits 25 px/s shift and 3 % zoom. A simulated pan measured 190 px/s and 30 % zoom and was refused.',
          'Bedrock: Nova 2 Lite through the global cross-region profile from Sydney (ap-southeast-2); $0.021 per synthetic match, $0.052 for a real 6-minute upload on the server (49 calls). Daily cap for all visitors: 300 calls and $1.00.',
          'AWS (ap-southeast-2, Sydney): one EC2 m7i-flex.large instance runs two containers, Caddy (HTTPS, Let’s Encrypt) in front of the Gaffer app. The app reaches Bedrock and S3 through the instance’s IAM role; no access key exists on the instance or in the image. S3 holds the replay clips, sample clips, detector model and the source of each deploy. CloudWatch keeps the logs for 14 days and counts analyses and Bedrock calls.',
          'The server costs about $3.10 a day while it runs (EC2, disk and IP), whatever the load.',
        ]}
      />
    </Section>
  )
}
