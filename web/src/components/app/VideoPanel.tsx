import { useEffect, useId, useRef, useState } from 'react'
import { Film, Upload, X } from 'lucide-react'
import Panel from './Panel'
import { EmptyState } from '../ui/States'
import { buttonClass } from '../ui/buttonStyles'
import type { PlaybackClock } from '../../lib/clock'
import { formatClock, parseClock } from '../../data/time'
import { offsetFromFileName, type VideoSource } from './transport'

/**
 * Plays a match video the coach picks from their own disk (never uploaded anywhere).
 * Videos are not part of the repo, so without a file this shows an empty state and the
 * minimap + timeline run from the stored positions instead.
 */
export default function VideoPanel({
  clock,
  defaultOffset,
  onVideo,
}: {
  clock: PlaybackClock
  defaultOffset: number
  onVideo: (v: VideoSource | null) => void
}) {
  const inputId = useId()
  const offsetId = useId()
  const videoRef = useRef<HTMLVideoElement>(null)
  const [file, setFile] = useState<{ url: string; name: string } | null>(null)
  const [offset, setOffset] = useState(defaultOffset)
  const [offsetText, setOffsetText] = useState(formatClock(defaultOffset))
  const [offsetSource, setOffsetSource] = useState<'default' | 'file name' | 'you'>('default')
  const [error, setError] = useState<string | null>(null)

  // release the object URL when the file changes or the panel unmounts
  useEffect(() => () => void (file && URL.revokeObjectURL(file.url)), [file])

  // the video drives the shared clock while it is loaded
  useEffect(() => {
    const el = videoRef.current
    if (!file || !el) return
    clock.attachSource(() => offset + el.currentTime)
    onVideo({ el, offset })
    return () => {
      clock.attachSource(null)
      onVideo(null)
    }
  }, [file, offset, clock, onVideo])

  const pick = (f: File | undefined) => {
    if (!f) return
    setError(null)
    const fromName = offsetFromFileName(f.name)
    if (fromName !== null) {
      setOffset(fromName)
      setOffsetText(formatClock(fromName))
      setOffsetSource('file name')
    }
    setFile({ url: URL.createObjectURL(f), name: f.name })
  }

  const commitOffset = () => {
    try {
      const v = parseClock(offsetText)
      setOffset(v)
      setOffsetSource('you')
    } catch {
      setOffsetText(formatClock(offset))
    }
  }

  return (
    <Panel
      title="Match video"
      id="video-title"
      actions={
        file && (
          <button
            type="button"
            onClick={() => setFile(null)}
            className="inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs text-muted hover:bg-surface-2 hover:text-text"
          >
            <X className="size-3.5" aria-hidden="true" /> Remove video
          </button>
        )
      }
    >
      {file ? (
        <div className="flex h-full flex-col">
          <video
            ref={videoRef}
            src={file.url}
            controls
            muted
            playsInline
            className="aspect-video w-full bg-black"
            onError={() => setError('This file cannot be played by the browser. Try an H.264 MP4.')}
            aria-label={`Local video ${file.name}`}
          />
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-xs text-muted">
            <span className="truncate font-mono" title={file.name}>
              {file.name}
            </span>
            <label htmlFor={offsetId} className="ml-auto">
              starts at match time
            </label>
            <input
              id={offsetId}
              value={offsetText}
              onChange={(e) => setOffsetText(e.target.value)}
              onBlur={commitOffset}
              onKeyDown={(e) => e.key === 'Enter' && commitOffset()}
              className="w-16 rounded-md border border-line bg-bg px-2 py-1 text-center font-mono text-text"
              inputMode="numeric"
              aria-describedby={`${offsetId}-src`}
            />
            <span id={`${offsetId}-src`}>({offsetSource === 'default' ? 'assumed' : `from ${offsetSource}`})</span>
          </div>
          {error && (
            <p role="alert" className="px-4 pb-3 text-xs text-danger">
              {error}
            </p>
          )}
        </div>
      ) : (
        <div className="grid aspect-video place-items-center">
          <EmptyState icon={<Film className="size-5" aria-hidden="true" />} title="No video loaded">
            <p>
              Match videos are not shipped with this demo. Choose a TeamTrack drone clip from your own disk to play it
              next to the pitch; it stays in your browser. The minimap and timeline run from the stored positions either
              way.
            </p>
            <label htmlFor={inputId} className={buttonClass('ghost', 'sm', 'mt-4 cursor-pointer focus-within:outline-2 focus-within:outline-accent')}>
              <Upload className="size-4" aria-hidden="true" /> Choose a video file
              <input
                id={inputId}
                type="file"
                accept="video/*"
                className="sr-only"
                onChange={(e) => pick(e.target.files?.[0])}
              />
            </label>
          </EmptyState>
        </div>
      )}
    </Panel>
  )
}
