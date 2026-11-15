import Section from './Section'
import Disclosure from '../ui/Disclosure'

const FAQ = [
  { q: 'Can I try Gaffer before uploading?', a: 'Yes. Explore the recorded TeamTrack match from the analyst desk, or choose a short sample in the upload dialog. The recorded example replays an existing analysis; sample uploads are processed when you submit them.' },
  { q: 'What kind of footage do I need?', a: 'Use an elevated, fixed camera that keeps the whole pitch in view, with clearly different team kits. The current upload flow is for short clips filmed from above. Panning, zooming and broadcast camera cuts are not supported. Check the footage guide in the upload dialog before choosing a file.' },
  { q: 'Can I connect a live camera?', a: 'The current version works with uploaded recordings and a recorded match replay. It does not connect to a live camera.' },
  { q: 'How long will my analysis take?', a: 'It depends on resolution, clip length and how busy the server is. Once processing starts, Gaffer shows an estimate based on the frames processed so far. Additional checks and any queue time are shown separately.' },
  { q: 'Does Gaffer choose my tactics or substitutions?', a: 'You make the decision. Gaffer estimates formations and highlights evidence for review. When supported, optional role advice uses your match objective and available roles; it does not identify a player to replace or make an automatic substitution.' },
  { q: 'How is my footage handled?', a: 'Uploaded video is processed on the hosted server. Raw uploads are deleted 24 hours after analysis finishes; results, evidence and saved coach responses remain. There is no face recognition or player-name extraction. Analyst questions are logged under a random visitor ID. Use footage you have permission to share; this prototype does not provide private club accounts.' },
  { q: 'How should I use the results?', a: 'Use them as a starting point for review, alongside the footage and your own match knowledge. This is an early product tested on limited footage: formations can be wrong and changes can be missed. Uncertain results are marked, and you can approve or reject alerts.' },
  { q: 'Does it measure possession or pressing?', a: 'No. The current analysis uses player positions and team shapes. It does not track the ball or establish possession, pressing or individual player identity.' },
]

export default function Faq() {
  return (
    <Section id="faq" eyebrow="FAQ" title="A few things before you start.">
      <ul className="mt-12 max-w-4xl divide-y divide-line border-y border-line">
        {FAQ.map(({ q, a }) => (
          <li key={q}>
            <Disclosure summary={<span className="text-xl font-semibold text-text">{q}</span>} summaryClassName="py-6 text-text">
              <p className="pb-6 text-lg leading-relaxed text-muted">{a}</p>
            </Disclosure>
          </li>
        ))}
      </ul>
    </Section>
  )
}
