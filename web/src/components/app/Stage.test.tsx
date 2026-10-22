import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import Stage, { CANNOT_PREVIEW, type LocalVideo } from './Stage'
import NoChangesCard from './NoChangesCard'
import { PlaybackClock } from '../../lib/clock'
import type { Transport } from './transport'

const transport = { playing: false, rate: 1, toggle() {}, seek() {}, setRate() {} } as Transport
const render = (video: LocalVideo | null) => renderToStaticMarkup(
  <Stage clock={new PlaybackClock({ min: 0, max: 180, start: 0 })} transport={transport} index={null} match={null}
    timeline={null} verifiedFor={() => null} onVideo={() => {}} video={video} onRemoveVideo={() => {}} onUpload={() => {}} />)

const upload: LocalVideo = { url: 'blob:x', name: 'my match.mp4', offset: 0 }

describe('upload result stage', () => {
  it('shows the video and the tactical pitch side by side, one transport, no picture-in-picture', () => {
    const html = render(upload)
    expect(html).toContain('data-layout="side-by-side"')
    expect(html).toContain('data-panel="video"')
    expect(html).toContain('data-panel="pitch"')
    expect(html).toContain('aria-label="Synchronized tactical map"')
    expect(html).not.toMatch(/absolute right-3|w-1\/3/) // the old corner inset
    expect(html).not.toMatch(/<video[^>]*\scontrols/) // no native controls: one clock
    expect(html).toContain('Match time') // the shared transport
    expect(html).toContain('Remove video')
  })

  it('stacks video over pitch below 900 px (one column), two equal columns from 900 px', () => {
    const grid = /data-layout="side-by-side"[^>]*class="([^"]+)"/.exec(render(upload))?.[1] ?? ''
    expect(grid.split(' ')).toContain('grid-cols-1')
    expect(grid.split(' ')).toContain('min-[900px]:grid-cols-2')
    const html = render(upload)
    expect(html.indexOf('data-panel="video"')).toBeLessThan(html.indexOf('data-panel="pitch"')) // video first
  })

  it('says plainly when the browser cannot play the file; the pitch keeps its panel', () => {
    const html = render({ ...upload, playable: false })
    expect(html).toContain(CANNOT_PREVIEW)
    expect(html).not.toContain('<video')
    expect(html).toContain('data-panel="pitch"')
    expect(html).toContain('data-layout="side-by-side"')
  })

  it('without a video the pitch is shown alone', () => {
    expect(render(null)).toContain('data-layout="pitch-only"')
  })
})

describe('no shape changes found', () => {
  it('explains a short clip with its length, and only then', () => {
    const short = renderToStaticMarkup(<NoChangesCard clipSeconds={45.4} />)
    expect(short).toContain('No shape changes found')
    expect(short).toContain('Gaffer needs about a minute after a change to confirm it; this clip is 45 s long.')
    expect(renderToStaticMarkup(<NoChangesCard clipSeconds={300} />)).not.toContain('about a minute')
    expect(renderToStaticMarkup(<NoChangesCard />)).not.toContain('about a minute')
  })
})
