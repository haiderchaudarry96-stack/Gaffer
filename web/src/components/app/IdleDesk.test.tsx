import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import IdleDesk from './IdleDesk'
import AmbientPitch from './AmbientPitch'

const noop = () => {}
const render = (reduced: boolean) => renderToStaticMarkup(
  <IdleDesk reduced={reduced} onLive={noop} onUpload={noop} onReview={noop} />)

describe('idle desk (/app before anything is started)', () => {
  it('offers the two ways in and the completed review as a secondary link', () => {
    const html = render(false)
    expect(html).toContain('Live analysis — recorded TeamTrack match (simulation)')
    expect(html).toContain('Upload your own video')
    expect(html).toContain('Review a completed analysis')
    expect(html).toContain('Waiting to start')
  })

  it('shows no alert, no timeline content and no real match data', () => {
    const html = render(false)
    for (const text of ['Formation change verified', 'Approve', 'checking', 'confirmed', 'evt_', 'White', 'Blue']) {
      expect(html).not.toContain(text)
    }
    const text = html.replace(/<[^>]+>/g, ' ')
    expect(text).not.toMatch(/\b\d-\d-\d/) // no formation reading anywhere
    expect(text).not.toMatch(/\b\d{1,2}:\d{2}\b/) // no match clock
    expect(html).not.toContain('shapes"') // no timeline segment lists
    expect(html).not.toMatch(/team-a|team-b/) // no team colours
    expect(html).not.toMatch(/<video|<canvas/) // no video, no real pitch canvas
  })

  it('the pitch is decorative: animated normally, a still image with reduced motion', () => {
    const moving = renderToStaticMarkup(<AmbientPitch reduced={false} />)
    expect(moving).toContain('data-decorative="true"')
    expect(moving).toContain('aria-hidden="true"')
    expect(moving).toMatch(/<animateTransform/)
    expect((moving.match(/<circle/g) ?? []).length).toBeGreaterThanOrEqual(10 + 1) // 11 dots + centre circle
    const still = renderToStaticMarkup(<AmbientPitch reduced={true} />)
    expect(still).not.toMatch(/<animate/)
    expect(still).toContain('Waiting to start')
    expect(render(true)).not.toMatch(/<animate/)
  })
})
