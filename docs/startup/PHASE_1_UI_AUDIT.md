# Phase 1 UI/UX audit

**Date:** 2026-11-14  
**Scope:** Gaffer startup-facing product presentation and existing React application flow. This is a local frontend and documentation audit; no backend contract or deployment work is in scope.

## Product and capability baseline

Gaffer is an early football video-analysis prototype. The current system accepts recorded match footage, detects and tracks player-like objects, classifies teams by kit colour, maps positions to a pitch, estimates formations and surfaces candidate changes with evidence for a coach to review. The API and analysis worker are FastAPI/Python; the interface is React, TypeScript, Vite and Tailwind CSS. MatchState and TacticalTimeline v1.0 remain frozen.

The current app has no live camera input. Its “Live analysis” path is a time-synchronized replay of stored TeamTrack footage and persisted analysis, while upload analysis is asynchronous server processing. OpenCV owns detection and verification; deterministic code owns final event verdicts. Bedrock supports bounded orchestration and explanation, not a calibrated tactical decision model. Role advice is conditional and heuristic. The camera must be elevated, fixed or drone-based, and show the full pitch. The pipeline has no ball, possession or pressing evidence.

The landing page already had strong product visuals (a tracked pitch, before/after comparison, product screenshot), motion preferences, dark/light design tokens, keyboard focus styles and clear technical caveats. It also led with a “before the scoreline” claim, hid evaluation/technology under “For judges,” named a “Judges & tech” nav item, promoted the competition in the footer, and called the recorded replay “Live analysis.” The result-card labels showed impressive numbers before the user saw their synthetic/one-match scope.

## Existing pages and flows

| Route / flow | Existing implementation | Audit findings |
|---|---|---|
| `/` landing page | Hero, analyst-desk preview, numbered workflow, evidence story, before/after slider, results, OpenCV/AWS cards, service runtime, limits, FAQ, CTA and footer | Mature reusable section/card components. Needs product-first language and results scope at the point of display. Runtime details remain server-derived. |
| `/app` analyst desk | Idle state, recorded TeamTrack replay, completed analysis, uploaded result, timeline, evidence, candidate/alert review, report, chat and dialogs | Most controls and states are already implemented and componentized. Rename the misleading “Live analysis” entry to “Recorded analysis”; retain the clear no-camera notice. |
| Upload | Local file/sample selection, validation, pitch confirmation, upload/progress and result | Existing flow is connected to documented API states. Keep it; use the footage guide and current size/duration constraints as the source of truth. |
| Error / not found | Reusable loading/error/empty state components and `/` return link | Existing baseline is functional. Detailed API failures can still be technical; coach-readable wording is a future usability review item. |
| Social metadata | `web/index.html` title, description, Open Graph and Twitter fields | Existing copy was technically accurate but generic. Update it to describe coaches and supported video-analysis outputs. |

## Competition-oriented references found

The frontend search found the following first-party presentation content:

- Landing navigation: “Judges & tech” and a direct GitHub entry in the primary nav.
- Landing section eyebrow and disclosure: “For judges and technical readers” / “Open judge and technical details.”
- Footer: “Built for the OpenCV AI Competition 2026, powered by AWS,” with a Devpost link.
- Landing results headline: a high-level false-alarm claim without its synthetic evaluation scope visible beside the figures.
- “Live analysis” labels for a recorded match, despite an explanatory notice inside setup.
- `web/index.html` social titles and descriptions; no explicit competition term was present, but the positioning has been updated.

Historical competition material remains in engineering and archive documentation (`docs/TECHNICAL_REPORT.md`, `docs/FINAL_AUDIT.md`, `docs/DEVPOST.md`, `docs/PLAN.md`, `RECORD.md`). It is not deleted or presented as the current product proposition.

## Accessibility, consistency and responsive audit

- The shared page already has a skip link, visible `:focus-visible`, semantic landmarks, labelled inputs/buttons, reduced-motion support, responsive Tailwind grids and reusable disclosure controls.
- The before/after interaction is a labelled keyboard-operable range input. Alert actions use real buttons and expose save errors with `role="alert"`.
- App dialogs and the analyst chat already have explicit close/focus handling. Existing page and component tests cover idle desk, replay timing, uploads, alerts, and data mapping.
- A recorded-footage disclaimer exists in the replay setup and completed result. The idle control and top navigation nevertheless gave the replay a real-time-sounding name; Phase 1 changes those visible labels.
- The main unresolved product-quality needs are a real unfamiliar-user test, automated accessibility scan, repeatable visual checks across desktop/tablet/mobile, and clearer presentation of infrastructure/runtime detail to non-technical users. These are reported as limitations if a check cannot be completed; they are not assumed to pass.

## Product claims and constraints

Supported language: recorded-footage analysis; player/object detections and anonymous tracking; team differentiation; pitch mapping; formation estimates; candidate changes; evidence display; coach approve/reject; grounded analyst chat when connected. Do not imply live-camera processing, player identity, automatic substitutions, ball possession, pressing detection, calibrated tactical advice, customer adoption or general performance across clubs.

Evaluation stays split by source: synthetic seeds 110–119 for false-alert/formation figures; TeamTrack drone footage from one match for real detection/team figures. The selected 15:00–21:00 demonstration window was chosen using ground-truth positions. The system misses a real Blue change at 18:50. Low-resolution 720p footage has lower formation agreement. These qualifications must remain discoverable near claims.

## API and integration boundaries

The UI uses the documented upload/create, pitch confirmation, analysis polling/result, alerts, chat, events, replay, report data and runtime endpoints in `docs/API.md`. Analysis status includes backend progress, ETA and failure state. No frontend change requires or proposes an API/schema change. The result visualizations consume existing data adapters and frozen MatchState/TacticalTimeline contracts; event persistence uses its separate schema.

No changes are permitted to OpenCV models, calibration/perception settings, tracking, formation/tactics, agent decision/verification rules, AWS infrastructure, or API response contracts for this phase.

## Phase 1 priorities

1. Lead with a clear, conservative coach-facing product description and remove competition/jury language from first-party product surfaces.
2. Put the replay’s recorded-footage status directly in its action label.
3. Expose what the existing measured results mean and which data source produced each metric.
4. Preserve useful technical details, limitations, attribution, consent/privacy and historical competition evidence in appropriate repository documentation.
5. Keep the current app flow intact; add UI regression checks and capture desktop/mobile evidence where available.
