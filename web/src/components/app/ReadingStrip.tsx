import type { ReadingStats } from '../../data/liveSession'

/** Live analysis session: what has been read so far, and where the readings come from. */
export default function ReadingStrip({ stats, playing }: { stats: ReadingStats; playing: boolean }) {
  return (
    <section aria-label="Reading status" className="rounded-(--radius-card) border border-line bg-surface px-4 py-3 sm:px-5">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <p className="flex items-center gap-2 text-sm font-semibold text-text">
          <span className={`size-2 rounded-full ${playing ? 'bg-accent motion-safe:animate-pulse' : 'bg-muted'}`} aria-hidden="true" />
          Gaffer is reading the footage
        </p>
        <p className="font-mono text-xs text-muted tabular">
          {stats.frames.toLocaleString('en')} frames read · {stats.detections.toLocaleString('en')} player detections so far
          · {stats.inView} in view now
        </p>
      </div>
      <p className="mt-1 text-xs text-muted">
        Detections and shapes come from Gaffer&apos;s OpenCV pipeline, run on this footage beforehand (about 7 min on a laptop CPU), and are revealed in match time. Ground-truth annotations are not used.
      </p>
    </section>
  )
}
