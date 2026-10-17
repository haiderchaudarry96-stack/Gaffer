import { splitCitations } from '../../data/alerts'

/** Renders text with [R2] / [evt_003] / [seg a-b] citations as small mono chips. */
export default function Cited({ text, onRef }: { text: string; onRef?: (ref: string) => void }) {
  return (
    <>
      {splitCitations(text).map((p, i) =>
        p.ref ? (
          onRef && /^R\d+$/.test(p.ref) ? (
            <button
              key={i}
              type="button"
              onClick={() => onRef(p.ref!)}
              className="mx-0.5 inline-flex rounded-md border border-line bg-surface-2 px-1.5 font-mono text-[11px] text-text align-[1px] hover:border-accent"
              aria-label={`Show trace step ${p.ref}`}
            >
              {p.ref}
            </button>
          ) : (
            <span
              key={i}
              className="mx-0.5 inline-flex rounded-md border border-line bg-surface-2 px-1.5 font-mono text-[11px] text-muted align-[1px]"
            >
              {p.ref}
            </span>
          )
        ) : (
          <span key={i}>{p.text}</span>
        ),
      )}
    </>
  )
}
