/** Clips shorter than this get the reason line (a change needs about a minute after it to confirm). */
export const SHORT_CLIP_S = 120

/** Right panel of a finished analysis with no candidate changes. */
export default function NoChangesCard({ clipSeconds }: { clipSeconds?: number }) {
  const short = clipSeconds !== undefined && clipSeconds > 0 && clipSeconds < SHORT_CLIP_S
  return (
    <article className="rounded-(--radius-card) border border-line bg-surface p-6">
      <h2 className="font-display text-2xl font-semibold text-text">No shape changes found</h2>
      <p className="mt-2 text-muted">The analysis has no candidate changes to show.</p>
      {short && (
        <p className="mt-2 text-muted">
          Gaffer needs about a minute after a change to confirm it; this clip is {Math.round(clipSeconds)} s long.
        </p>
      )}
    </article>
  )
}
