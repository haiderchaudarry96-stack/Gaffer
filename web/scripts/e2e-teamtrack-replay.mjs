/* global document */
/* global HTMLInputElement */
/* global window */
import assert from 'node:assert/strict'
import { chromium } from 'playwright-core'

const base = process.env.BASE_URL ?? 'http://127.0.0.1:8011'
const executablePath = process.env.CHROMIUM_PATH
const expectReadyAdvice = process.env.N5_READY_ADVICE === '1'
const expectSavedResponse = process.env.N5_EXPECT_SAVED_RESPONSE === '1'
const expectContextMismatch = process.env.N5_CONTEXT_MISMATCH === '1'
const targetEventId = process.env.N5_EVENT_ID
const responseDecision = process.env.N5_RESPONSE_DECISION ?? 'approved'
const responseNote = `N5 browser-to-database restart ${responseDecision === 'approved' ? 'acceptance' : 'rejection'}`
if (!executablePath) throw new Error('Set CHROMIUM_PATH to an installed Chromium, Chrome or Edge executable')
const browser = await chromium.launch({ executablePath, headless: true })

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' })
  const failures = []
  page.on('pageerror', (error) => failures.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') failures.push(message.text())
  })

  await page.goto(base)
  await page.getByRole('heading', { name: 'Evidence, results, and how the system works' }).waitFor()
  assert.equal(await page.getByRole('heading', { name: /Far fewer false alarms/ }).count(), 0,
    'evaluation headline is tucked into the judge brief by default')
  assert.equal(await page.getByRole('heading', { name: /OpenCV 5 does the seeing/ }).count(), 0,
    'technical headline is tucked into the judge brief by default')
  await page.getByRole('link', { name: 'Judges & tech' }).click()
  await page.getByRole('button', { name: 'Open judge and technical details' }).click()
  await page.getByRole('heading', { name: /Far fewer false alarms/ }).waitFor()
  await page.getByRole('heading', { name: /OpenCV 5 does the seeing/ }).waitFor()
  await page.goto(`${base}/app?paused=1`)
  assert.equal(await page.evaluate(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches), true,
    'the browser run requests reduced motion')
  const openLiveSetup = page.getByRole('button', { name: 'Live analysis' })
  await openLiveSetup.focus()
  await page.keyboard.press('Enter')
  const setup = page.getByRole('dialog', { name: 'Set up Live analysis' })
  await setup.waitFor()
  assert.equal(await page.evaluate(() => {
    const dialog = document.querySelector('dialog[open]')
    return Boolean(dialog?.contains(document.activeElement))
  }), true, 'keyboard focus enters the setup dialog')
  await page.keyboard.press('Tab')
  const keyboardFocus = await page.evaluate(() => {
    const dialog = document.querySelector('dialog[open]')
    const active = document.activeElement
    const style = active ? window.getComputedStyle(active) : null
    return { inside: Boolean(dialog?.contains(active)), outlineWidth: parseFloat(style?.outlineWidth ?? '0'),
      outlineStyle: style?.outlineStyle }
  })
  assert(keyboardFocus.inside, 'Tab moves between setup controls inside the modal')
  assert(keyboardFocus.outlineWidth >= 2 && keyboardFocus.outlineStyle !== 'none',
    'keyboard focus has a visible outline')
  const setupText = await setup.innerText()
  assert.match(setupText, /fixed elevated position/i, 'setup describes elevated camera placement')
  assert.match(setupText, /entire pitch/i, 'setup says the entire pitch must be visible')
  assert.match(setupText, /different jerseys/i, 'setup requires visually different team jerseys')
  assert.match(setupText, /No camera is connected/i, 'setup does not claim a live camera is connected')
  await page.locator('#coach-side').selectOption(expectContextMismatch ? 'home' : 'away')
  await page.locator('#match-objective').selectOption(expectContextMismatch ? 'balanced' : 'chase')
  await setup.getByRole('checkbox', { name: expectContextMismatch ? 'defender' : 'attacker' }).check()
  await page.getByRole('button', { name: 'Start recorded match analysis' }).click()

  const video = page.locator('video[aria-label^="Recorded TeamTrack"]')
  await video.waitFor()
  await page.waitForFunction(() => {
    const el = document.querySelector('video[aria-label^="Recorded TeamTrack"]')
    return el && el.readyState >= 1
  }, null, { timeout: 60_000 })
  await page.getByText('Recorded TeamTrack footage · replay, not a live camera').waitFor()

  const videoBox = await video.boundingBox()
  const mapBox = await page.getByLabel('Synchronized tactical map').boundingBox()
  assert(videoBox && mapBox && videoBox.x + videoBox.width <= mapBox.x + 2,
    'recorded video and tactical map are adjacent panels')
  await page.setViewportSize({ width: 375, height: 812 })
  const mobileLayout = await page.evaluate(() => {
    const video = document.querySelector('video[aria-label^="Recorded TeamTrack"]')?.getBoundingClientRect()
    const map = document.querySelector('[aria-label="Synchronized tactical map"]')?.getBoundingClientRect()
    const offenders = Array.from(document.body.querySelectorAll('*')).map((element) => {
      const rect = element.getBoundingClientRect()
      return { tag: element.tagName, id: element.id, className: String(element.className).slice(0, 120),
        right: Math.round(rect.right), width: Math.round(rect.width),
        text: (element.textContent ?? '').trim().slice(0, 70) }
    }).filter((item) => item.width > 0 && item.right > window.innerWidth + 2).slice(0, 12)
    return { overflow: document.documentElement.scrollWidth - window.innerWidth,
      stacked: Boolean(video && map && video.bottom <= map.top + 2), offenders }
  })
  if (mobileLayout.overflow > 2) console.log('mobile overflow elements:', JSON.stringify(mobileLayout.offenders))
  await page.screenshot({ path: '../outputs/n5-validation/mobile-layout.png', fullPage: true })
  assert(mobileLayout.overflow <= 2, `mobile replay has no horizontal overflow (${mobileLayout.overflow}px)`)
  assert(mobileLayout.stacked, 'mobile replay stacks the video and tactical map')
  await page.setViewportSize({ width: 1440, height: 1000 })

  const slider = page.getByLabel('Match time')
  const seek = async (seconds) => {
    await slider.evaluate((el, value) => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
      setter?.call(el, String(value))
      el.dispatchEvent(new Event('input', { bubbles: true }))
      el.dispatchEvent(new Event('change', { bubbles: true }))
    }, seconds)
    await page.waitForFunction((target) => {
      const input = document.querySelector('input[type="range"]')
      return input && Math.abs(Number(input.value) - target) <= 0.26
    }, seconds, { timeout: 5_000 })
  }
  const clipLabel = (index) => {
    const start = 900 + index * 30
    const end = start + 30
    return `${String(start).padStart(4, '0')}-${String(end).padStart(4, '0')}`
  }
  const waitClip = async (id) => page.waitForFunction((clipId) => {
    const el = document.querySelector('video[aria-label^="Recorded TeamTrack"]')
    return el?.currentSrc.includes(clipId) && el.readyState >= 1
  }, id, { timeout: 30_000 })
  const waitClipAt = async (id, localTime) => page.waitForFunction(({ clipId, seconds }) => {
    const el = document.querySelector('video[aria-label^="Recorded TeamTrack"]')
    return el?.currentSrc.includes(clipId) && el.readyState >= 1
      && Math.abs(el.currentTime - seconds) < 0.6
  }, { clipId: id, seconds: localTime }, { timeout: 30_000 })
  const waitPlayingClip = async (id) => page.waitForFunction((clipId) => {
    const el = document.querySelector('video[aria-label^="Recorded TeamTrack"]')
    return el?.currentSrc.includes(clipId) && el.readyState >= 2 && !el.paused && el.currentTime > 0.05
  }, id, { timeout: 30_000 })

  for (let i = 0; i < 12; i += 1) {
    await seek(900 + i * 30 + 5)
    await waitClip(clipLabel(i))
    const local = await video.evaluate((el) => el.currentTime)
    assert(Math.abs(local - 5) < 0.6, `clip ${clipLabel(i)} seeks to local second 5 (got ${local})`)
  }

  for (let i = 0; i < 11; i += 1) {
    const boundary = 930 + i * 30
    await seek(boundary)
    await waitClip(clipLabel(i + 1))
    const local = await video.evaluate((el) => el.currentTime)
    assert(local < 0.5, `boundary ${boundary} starts the next clip at local zero (got ${local})`)
  }

  for (const [rate, previousClip] of [[1, 0], [2, 4], [4, 8]]) {
    await page.getByRole('button', { name: `${rate}×` }).click()
    const actual = await video.evaluate((el) => el.playbackRate)
    assert.equal(actual, rate, `${rate}× rate is applied to the current source`)
    await seek(900 + previousClip * 30 + 5)
    await waitClipAt(clipLabel(previousClip), 5)
  }

  const replay = await page.evaluate(async () => {
    const response = await fetch('/api/replay/teamtrack')
    const manifest = await response.json()
    const eventsResponse = await fetch(`/api/events?match_id=${encodeURIComponent(manifest.match_id)}&limit=100`)
    return { manifest, events: (await eventsResponse.json()).events }
  })
  assert.equal(replay.manifest.clips.length, 12, 'backend returns all 12 source clips')
  const target = targetEventId
    ? replay.events.find((event) => event.event_id === targetEventId)
    : replay.events.find((event) => event.team === 'home'
      && event.from_formation === '4-4-2' && event.to_formation === '3-4-3'
      && event.verification_match_time_s !== null)
  assert(target, 'the authentic OpenCV TeamTrack event and evidence boundary are stored')

  await seek(target.candidate_time_s - 0.5)
  await page.waitForTimeout(350)
  const targetLabel = new RegExp(`${target.team_name} ${target.from_formation} to ${target.to_formation}`)
  assert.equal(await page.getByRole('button', { name: targetLabel }).count(), 0,
    'the target event is not exposed before its candidate time')

  await seek(target.candidate_time_s)
  await page.getByRole('button', { name: targetLabel }).waitFor()
  await page.getByRole('button', { name: targetLabel }).click()
  await page.getByRole('heading', { name: /Possible formation change/ }).waitFor()
  await seek(Math.max(target.candidate_time_s, target.verification_match_time_s - 0.5))
  await page.getByText(/Provisional.*checking/).waitFor()
  await seek(target.verification_match_time_s)
  const finalHeading = target.status === 'confirmed' ? 'Formation change verified'
    : target.status === 'rejected' ? 'Candidate not confirmed' : 'Formation change remains uncertain'
  await page.getByRole('heading', { name: finalHeading }).waitFor()
  const posture = page.getByRole('region', { name: 'Tactical posture assessment' })
  await posture.getByText(expectReadyAdvice ? 'defensive' : /unclear/i,
    expectReadyAdvice ? { exact: true } : undefined).waitFor()
  if (expectReadyAdvice) {
    assert.equal(await posture.getByText('opencv_metrics.before.defensive_line_m').count(), 0,
      'OpenCV citations are collapsed by default')
    await posture.getByRole('button', { name: 'OpenCV evidence' }).click()
    await posture.getByText('opencv_metrics.before.defensive_line_m').waitFor()
  }
  const advice = page.getByRole('region', { name: 'Optional role advice' })
  if (expectReadyAdvice) {
    await advice.getByText(/^If the opponent's defensive posture continues/i).waitFor()
    await advice.getByText(/Consider replacing a defender with an available attacker/i).waitFor()
    assert.equal(await advice.getByText('opencv_metrics.before.defensive_line_m').count(), 0,
      'cited posture evidence is collapsed by default')
    await advice.getByRole('button', { name: 'Cited posture evidence' }).click()
    await advice.getByText('opencv_metrics.before.defensive_line_m').waitFor()
    const adviceText = await advice.innerText()
    assert.doesNotMatch(adviceText, /automatically|player\s+\d+/i,
      'the suggestion stays conditional and role-level, with no named-player or automatic-substitution claim')
    if (expectSavedResponse) {
      await advice.getByText(`Coach ${responseDecision} this suggestion.`).waitFor()
      await advice.getByText(responseNote).waitFor()
    } else if (expectContextMismatch) {
      await advice.getByText(/This advice already has a saved coach response/i).waitFor()
      assert.doesNotMatch(await advice.innerText(), /Tactical advice failed|HTTP 409/i,
        'a changed setup explains the saved context instead of showing an API failure')
      await advice.getByText(`Coach ${responseDecision} this suggestion.`).waitFor()
      await advice.getByText(responseNote).waitFor()
    } else {
      await advice.getByRole('textbox', { name: 'Optional note for this suggestion' })
        .fill(responseNote)
      await advice.getByRole('button', {
        name: responseDecision === 'approved' ? 'Accept suggestion' : 'Reject suggestion',
      }).click()
      await advice.getByText(`Coach ${responseDecision} this suggestion.`).waitFor()
      await advice.getByText(responseNote).waitFor()
    }
  } else {
    await posture.getByText(/Bedrock output was unavailable|deterministic fallback/i).waitFor()
    await advice.getByText(/No role suggestion for this event/i).waitFor()
    assert.equal(await advice.getByRole('button', { name: /Accept suggestion|Reject suggestion/ }).count(), 0,
      'unavailable Bedrock posture cannot produce an actionable role suggestion')
  }
  const persisted = await page.evaluate(async (recordId) => {
    const response = await fetch(`/api/events/${encodeURIComponent(recordId)}`)
    return response.json()
  }, target.record_id)
  assert.equal(persisted.status, 'confirmed', 'formation verification remains distinct and confirmed')
  if (expectReadyAdvice) {
    assert.equal(persisted.posture_status, 'completed', 'test fixture posture is separately persisted')
    assert.equal(persisted.recommendation_status, 'ready', 'supported advice remains a separate record')
    assert.deepEqual(persisted.recommendation.citations,
      persisted.posture_result.citations, 'advice cites the persisted N3 evidence exactly')
    assert.deepEqual(persisted.recommendation.action,
      { consider_replacing: 'defender', with_available_role: 'attacker' },
      'advice remains conditional and role-level')
    assert.equal(persisted.recommendation.coach_response.decision, responseDecision)
    assert.equal(persisted.recommendation.coach_response.note, responseNote)
  } else {
    assert.equal(persisted.posture_status, 'failed', 'failed Bedrock state remains explicit in storage')
    assert.equal(persisted.posture_result.posture, 'unclear', 'fallback does not invent a posture')
    assert.equal(persisted.recommendation_status, 'withheld', 'N4 stores a withheld, non-actionable result')
    assert.equal(persisted.recommendation.action, null, 'withheld N4 result contains no action')
  }
  assert.equal(persisted.recommendation.context.objective, 'chase', 'coach context persists')

  await page.getByRole('group', { name: 'Playback speed' }).getByRole('button').nth(0).click()
  await seek(929.5)
  await waitClipAt(clipLabel(0), 29.5)
  await video.evaluate((el) => {
    if (Number.isFinite(el.duration)) el.currentTime = Math.max(0, el.duration - 0.15)
  })
  await page.getByRole('button', { name: 'Play' }).click()
  await waitPlayingClip(clipLabel(1))
  const clockAtBoundary = Number(await slider.inputValue())
  assert(Math.abs(clockAtBoundary - 930) < 1.5,
    `1× playback crosses into the next clip without a match-clock jump (${clockAtBoundary})`)
  for (let currentClip = 1; currentClip < 11; currentClip += 1) {
    await video.evaluate((el) => { el.currentTime = el.duration - 0.15 })
    const nextClip = currentClip + 1
    await waitPlayingClip(clipLabel(nextClip))
    const expectedTime = 900 + nextClip * 30
    const observedTime = Number(await slider.inputValue())
    assert(Math.abs(observedTime - expectedTime) < 1.5,
      `natural transition to ${expectedTime}s keeps the shared clock aligned (${observedTime})`)
  }
  await video.evaluate((el) => { el.currentTime = el.duration - 0.15 })
  await page.waitForFunction(() => {
    const el = document.querySelector('video[aria-label^="Recorded TeamTrack"]')
    return el?.currentSrc.includes('1230-1260') && el.paused && el.currentTime >= el.duration - 0.05
  }, null, { timeout: 30_000 })
  assert(Math.abs(Number(await slider.inputValue()) - 1260) < 1.5,
    'the final segment ends at the 1260s match-clock boundary')


  assert.deepEqual(failures, [], `browser reported no errors: ${failures.join('; ')}`)
  console.log(`PASS: 12 clips, 11 seek boundaries and 11 playback handoffs, 1×/2×/4×, and event reveal at ${target.verification_match_time_s}s`)
} finally {
  await browser.close()
}
