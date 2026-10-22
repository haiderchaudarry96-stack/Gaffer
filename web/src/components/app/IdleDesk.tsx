import { ArrowRight, Upload, Video } from 'lucide-react'
import AmbientPitch from './AmbientPitch'

/**
 * /app before anything is started: no match data, no timeline content, no alert. A decorative
 * pitch and the two ways in (live-style session on recorded footage, or an upload); the
 * finished analysis is a secondary choice.
 */
export default function IdleDesk({
  reduced,
  onLive,
  onUpload,
  onReview,
}: {
  reduced: boolean
  onLive: () => void
  onUpload: () => void
  onReview: () => void
}) {
  return (
    <>
      <section aria-labelledby="idle-title" className="grid gap-6 xl:col-span-2 xl:grid-cols-[minmax(0,1fr)_440px] xl:gap-8">
        <div className="overflow-hidden rounded-(--radius-card) border border-line bg-surface">
          <div className="mx-auto aspect-[110/73] w-[calc(100%-1.5rem)] max-w-[calc(46vh*110/73)] py-3 sm:w-[calc(100%-2rem)]">
            <AmbientPitch reduced={reduced} className="size-full" />
          </div>
        </div>
        <div className="flex flex-col justify-center rounded-(--radius-card) border border-line bg-surface p-6 sm:p-7">
          <h2 id="idle-title" className="font-display text-2xl font-semibold text-text">Start an analysis</h2>
          <p className="mt-2 text-muted">
            Nothing is shown until you start: dots, shapes and alerts appear as the footage is read.
          </p>
          <div className="mt-6 grid gap-3">
            <button
              type="button"
              onClick={onLive}
              className="group flex min-h-14 items-center gap-3 rounded-2xl bg-accent px-5 py-3 text-left font-semibold text-on-accent transition-transform hover:-translate-y-0.5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-ink motion-reduce:transition-none motion-reduce:hover:translate-y-0"
            >
              <Video className="size-5 shrink-0" aria-hidden="true" />
              <span>Live analysis — recorded TeamTrack match (simulation)</span>
              <ArrowRight className="ml-auto size-4 shrink-0" aria-hidden="true" />
            </button>
            <button
              type="button"
              onClick={onUpload}
              className="flex min-h-14 items-center gap-3 rounded-2xl border-2 border-text px-5 py-3 text-left font-semibold text-text transition-colors hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-ink"
            >
              <Upload className="size-5 shrink-0" aria-hidden="true" />
              <span>Upload your own video</span>
              <ArrowRight className="ml-auto size-4 shrink-0" aria-hidden="true" />
            </button>
          </div>
          <p className="mt-4 text-sm text-muted">
            The live analysis replays recorded footage; no camera is connected.
          </p>
          <button
            type="button"
            onClick={onReview}
            className="mt-5 w-fit text-sm font-medium text-accent-ink underline underline-offset-4 hover:text-text focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-ink"
          >
            Review a completed analysis
          </button>
        </div>
      </section>
      <section aria-labelledby="idle-timeline-title" className="rounded-(--radius-card) border border-line bg-surface px-4 py-4 sm:px-6 xl:col-span-2">
        <h2 id="idle-timeline-title" className="font-sans text-base font-semibold tracking-normal text-text">Shape timeline</h2>
        <p className="mt-2 text-sm text-muted">Empty: shapes and changes fill in here once a session starts.</p>
        <div className="mt-3 h-9 rounded-md border border-dashed border-line" aria-hidden="true" />
      </section>
    </>
  )
}
