import { CheckCircle2, Clock3, Info, ShieldAlert, XCircle } from 'lucide-react'
import { useState } from 'react'
import { formatClock } from '../../data/time'
import { decideRoleRecommendation, postureVisibleAt,
  type PersistedEvent, type ReplayEventState } from '../../data/teamtrack'
import Disclosure from '../ui/Disclosure'

type VisibleEventState = Exclude<ReplayEventState, { kind: 'upcoming' }>

function coachReadableWithheldReason(reason?: string | null): string {
  const copy: Record<string, string> = {
    'Select which team you are coaching.': 'Choose which side you coach first.',
    'Select a match objective before advice can be considered.': 'Choose a match objective first.',
    'Enter at least one available substitute role.': 'Add an available role in setup first.',
    'The formation event is not deterministically confirmed.':
      'This formation change has not been confirmed, so it is too early to base advice on it.',
    'Supported tactical posture evidence is not available.':
      'The posture read is unclear or unavailable; suggesting a role change would be a guess.',
    'The posture assessment does not contain enough validated evidence.':
      'The posture evidence did not pass its checks, so a role suggestion would be a guess.',
    "This event is your team's change; this response rule covers opponent changes.":
      'This rule only considers the opponent’s formation changes.',
    'No available attacking substitute role was entered.':
      'Add an available attacker role in setup before considering this option.',
    'No available defensive substitute role was entered.':
      'Add an available defender role in setup before considering this option.',
    'No balanced-objective role rule is supported by the current evidence.':
      'There is no role rule for the balanced objective yet.',
    'The current objective and supported posture do not match a documented role-advice rule.':
      'This posture and objective do not match a supported role rule.',
  }
  return reason ? (copy[reason] ?? reason) : 'The evidence and coach context do not support a role option.'
}

export default function RecordedEventCard({
  event,
  state,
  coachSide,
  matchTimeS,
  onRefresh,
  recommendationError,
  recommendationNotice,
}: {
  event: PersistedEvent
  state: VisibleEventState
  coachSide: 'home' | 'away' | ''
  matchTimeS: number
  onRefresh: () => void
  recommendationError?: string
  recommendationNotice?: string
}) {
  const isOwn = coachSide !== '' && event.team === coachSide
  const [note, setNote] = useState('')
  const [decisionBusy, setDecisionBusy] = useState(false)
  const [decisionError, setDecisionError] = useState<string | null>(null)
  const title = state.kind === 'checking'
    ? 'Possible formation change · checking'
    : state.status === 'confirmed'
      ? 'Formation change verified'
      : state.status === 'rejected'
        ? 'Candidate not confirmed'
        : 'Formation change remains uncertain'
  const Icon = state.kind === 'checking'
    ? Clock3
    : state.status === 'confirmed'
      ? CheckCircle2
      : state.status === 'rejected'
        ? XCircle
        : ShieldAlert
  const color = state.kind === 'checking'
    ? 'border-warn/40 bg-warn/5 text-warn'
    : state.status === 'confirmed'
      ? 'border-accent/40 bg-accent/5 text-accent-ink'
      : state.status === 'rejected'
        ? 'border-danger/40 bg-danger/5 text-danger'
        : 'border-warn/40 bg-warn/5 text-warn'
  const postureVisible = state.kind === 'decided' && postureVisibleAt(event, matchTimeS)
  const posture = event.posture_result
  const recommendation = event.recommendation

  const decide = async (decision: 'approved' | 'rejected') => {
    if (!recommendation) return
    setDecisionBusy(true)
    setDecisionError(null)
    try {
      await decideRoleRecommendation(event.record_id, recommendation.recommendation_id,
        decision, note.trim() || undefined)
      onRefresh()
    } catch (error) {
      setDecisionError(error instanceof Error ? error.message : 'Could not save your advice response.')
    } finally {
      setDecisionBusy(false)
    }
  }

  return (
    <article className="rounded-(--radius-card) border border-line bg-surface p-6" aria-live="polite">
      <div className="flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-wide">
        <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 ${color}`}>
          <Icon className="size-3.5" aria-hidden="true" />
          {state.kind === 'checking' ? 'Provisional · checking' : state.status}
        </span>
        <span className="text-muted">{coachSide === '' ? event.team_name : isOwn ? 'Your team' : 'Opponent'} · {event.team_name}</span>
      </div>
      <h2 className="mt-4 font-display text-2xl font-semibold text-text">{title}</h2>
      <p className="mt-3 text-lg text-text">
        {event.from_formation ?? 'Shape'} <span aria-label="to">→</span> {event.to_formation ?? 'new shape'}
      </p>
      <p className="mt-2 text-sm text-muted">
        OpenCV event at {formatClock(event.candidate_time_s)}. This is a formation-change record; it does not by itself describe tactical intent.
      </p>
      {state.kind === 'checking' && event.verification_match_time_s === null && (
        <p className="mt-4 rounded-xl border border-line bg-bg px-4 py-3 text-sm text-muted">
          No trustworthy match-time evidence boundary is stored, so this replay keeps the formation
          event provisional and the tactical posture withheld as unclear.
        </p>
      )}
      {state.kind === 'checking' && event.verification_match_time_s !== null && (
        <p className="mt-4 text-sm text-muted">
          Verification can appear after the recorded evidence window ends at {formatClock(event.verification_match_time_s)}.
        </p>
      )}
      {postureVisible && (
        <section className="mt-5 rounded-xl border border-line bg-bg p-4" aria-label="Tactical posture assessment">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold text-text">Tactical posture</h3>
            <span className="rounded-full border border-line px-2 py-0.5 text-xs uppercase tracking-wide text-muted">
              advisory
            </span>
            {posture?.source === 'deterministic_fallback' && (
              <span className="rounded-full border border-warn/40 bg-warn/5 px-2 py-0.5 text-xs text-warn">
                evidence fallback
              </span>
            )}
          </div>
          {event.status !== 'confirmed' ? (
            <p className="mt-3 text-sm text-muted">
              Posture was not assessed because the deterministic verifier did not confirm this formation change.
            </p>
          ) : event.posture_status === 'pending' ? (
            <p className="mt-3 text-sm text-muted">Assessing the stored OpenCV shape metrics…</p>
          ) : posture ? (
            <>
              <p className="mt-2 text-lg font-medium capitalize text-text">{posture.posture}</p>
              <p className="mt-2 text-sm text-text">{posture.explanation}</p>
              <p className="mt-2 text-xs text-muted">
                Evidence strength {posture.evidence_strength} / 1; this is not a calibrated probability.
                {posture.source === 'bedrock' ? ' Assessed by Amazon Bedrock.' : ' Bedrock output was unavailable or did not pass evidence checks.'}
              </p>
              {posture.citations.length > 0 && (
                <Disclosure
                  className="mt-4"
                  title="OpenCV evidence"
                  summaryClassName="w-fit rounded-lg border border-line px-3 py-2 text-sm font-medium text-text hover:bg-surface focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-ink"
                  summary={<span className="inline-flex items-center gap-2"><Info className="size-4" aria-hidden="true" />OpenCV evidence</span>}
                >
                  <ul className="mt-3 space-y-2 rounded-lg border border-line bg-surface p-3">
                    {posture.citations.map((citation, index) => (
                      <li key={`${citation.metric_path}-${index}`} className="text-xs text-text">
                        <code className="break-all">{citation.metric_path}</code>
                        <span> = {String(citation.value)} {citation.unit}</span>
                        <span className="block text-muted">
                          Match time {formatClock(citation.match_time_window_s[0])}–{formatClock(citation.match_time_window_s[1])}
                        </span>
                      </li>
                    ))}
                  </ul>
                </Disclosure>
              )}
              {posture.limitations.length > 0 && (
                <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-muted">
                  {posture.limitations.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}
                </ul>
              )}
            </>
          ) : event.posture_status === 'unavailable' || event.posture_status === 'failed' ? (
            <p className="mt-3 text-sm text-muted">
              Posture is unclear. Bedrock analysis did not complete; the formation verification remains unchanged.
            </p>
          ) : (
            <p className="mt-3 text-sm text-muted">
              This verified formation change has not been assessed for tactical posture yet.
            </p>
          )}
        </section>
      )}
      {postureVisible && (
        <section className="mt-5 rounded-xl border border-line bg-bg p-4" aria-label="Optional role advice">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold text-text">Optional role advice</h3>
            <span className="rounded-full border border-line px-2 py-0.5 text-xs uppercase tracking-wide text-muted">conditional</span>
          </div>
          {recommendationNotice && (
            <p role="status" className="mt-3 rounded-lg border border-line px-3 py-2 text-sm text-muted">
              {recommendationNotice}
            </p>
          )}
          {event.recommendation_status === 'pending' ? (
            <p className="mt-3 text-sm text-muted">Preparing an evidence-checked option…</p>
          ) : recommendationError ? (
            <p role="alert" className="mt-3 text-sm text-danger">{recommendationError}</p>
          ) : event.recommendation_status === 'not_requested' || !recommendation ? (
            <p className="mt-3 text-sm text-muted">Advice is being checked against your objective and available substitute roles.</p>
          ) : recommendation.status === 'withheld' ? (
            <p className="mt-3 text-sm text-muted">
              No role suggestion for this event. {coachReadableWithheldReason(recommendation.withheld_reason)}
              {' '}Gaffer only offers a conditional role option when the confirmed formation, supported posture evidence,
              your objective, and an available role align. It does not select a named player or make a substitution.
            </p>
          ) : (
            <>
              <p className="mt-3 text-sm font-medium text-text">{recommendation.condition}</p>
              <p className="mt-2 text-sm text-text">
                Consider replacing a {recommendation.action?.consider_replacing} with an available {recommendation.action?.with_available_role}.
              </p>
              <p className="mt-2 text-sm text-muted">{recommendation.rationale}</p>
              <p className="mt-2 text-xs text-muted">
                {recommendation.context.objective} objective · {recommendation.posture} posture · Evidence strength {recommendation.evidence_strength}/1; not a calibrated probability.
              </p>
              {recommendation.citations.length > 0 && (
                <Disclosure
                  className="mt-3"
                  title="Cited posture evidence"
                  summaryClassName="w-fit rounded-lg border border-line px-3 py-2 text-sm font-medium text-text hover:bg-surface focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-ink"
                  summary={<span className="inline-flex items-center gap-2"><Info className="size-4" aria-hidden="true" />Cited posture evidence</span>}
                >
                  <ul className="mt-3 space-y-2 rounded-lg border border-line bg-surface p-3">
                    {recommendation.citations.map((citation, index) => (
                      <li key={`${citation.metric_path}-${index}`} className="text-xs text-text">
                        <code className="break-all">{citation.metric_path}</code>
                        <span> = {String(citation.value)} {citation.unit}</span>
                        <span className="block text-muted">Match time {formatClock(citation.match_time_window_s[0])}–{formatClock(citation.match_time_window_s[1])}</span>
                      </li>
                    ))}
                  </ul>
                </Disclosure>
              )}
              {recommendation.coach_response ? (
                <div className="mt-4 rounded-lg border border-line px-3 py-2 text-sm">
                  <strong>Coach {recommendation.coach_response.decision} this suggestion.</strong>
                  {recommendation.coach_response.note && <p className="mt-1 text-muted">{recommendation.coach_response.note}</p>}
                </div>
              ) : (
                <div className="mt-4 space-y-3">
                  <label htmlFor={`recommendation-note-${event.record_id}`} className="block text-xs font-medium text-muted">Optional note for this suggestion</label>
                  <textarea id={`recommendation-note-${event.record_id}`} maxLength={500} value={note}
                    onChange={(e) => setNote(e.target.value)} rows={2}
                    className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-text"
                    placeholder="Add a note (optional)" />
                  <div className="flex flex-wrap gap-2">
                    <button type="button" disabled={decisionBusy} onClick={() => void decide('approved')}
                      className="rounded-lg bg-accent px-3 py-2 text-sm font-semibold text-accent-ink disabled:opacity-50">Accept suggestion</button>
                    <button type="button" disabled={decisionBusy} onClick={() => void decide('rejected')}
                      className="rounded-lg border border-line px-3 py-2 text-sm font-semibold text-text disabled:opacity-50">Reject suggestion</button>
                  </div>
                  {decisionError && <p role="alert" className="text-sm text-danger">{decisionError}</p>}
                </div>
              )}
            </>
          )}
        </section>
      )}
    </article>
  )
}
