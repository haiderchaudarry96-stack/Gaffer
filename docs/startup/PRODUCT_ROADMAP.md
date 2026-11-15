# Gaffer product roadmap

This is a proposed product-development sequence, not a commitment or a statement that these features exist. Phase 1 is the current local UI and product-positioning pass. Further work needs product-owner prioritization and evidence before being described as available.

## Phase 1 — Product presentation and interface foundations

**Status:** in progress in `feature/startup-ui-phase1`.

- Present Gaffer as an early football video-analysis product prototype for coaches and analysts.
- Keep synthetic and real-footage evidence separate and visible.
- Label recorded replay honestly; preserve the upload, evidence review, approval, report and chat workflows.
- Record technical limitations and follow-up research without changing the CV pipeline.

## Candidate next steps

### 2. Coach discovery and workflow validation

- Interview coaches and match analysts about when they review footage, how they define useful alerts, and what evidence they trust.
- Observe upload setup, pitch confirmation, uncertainty, report and alert decisions with unfamiliar users.
- Test terminology, alert usefulness and mobile review before adding workflow complexity.

### 3. Evaluation across footage and teams

- Build a licensed, consented dataset spanning different grounds, kits, cameras, resolutions and lighting.
- Pre-register train/validation/test splits and report per-condition detection, tracking, team classification, formation agreement, event recall, false alerts and runtime.
- Set release criteria with domain reviewers; avoid treating a single-match demonstration or synthetic results as product-level validation.

### 4. Privacy, access and customer data lifecycle

- Specify team/club tenancy, authentication, authorization, retention, export and deletion needs before adding accounts or persistent match libraries.
- Review privacy notices, consent, youth-footage handling, incident response and regional storage requirements with qualified advisers.

### 5. Product reliability and operations

- Measure queue latency and cost across clip length/resolution on representative infrastructure.
- Improve retry, cancellation, capacity and operational visibility using measured failure cases.
- Define availability, support and data-recovery expectations before making service-level claims.

### 6. Research-led perception and tactical expansion

- Use `CV_RESEARCH_BACKLOG.md` to prioritize benchmarked CV work.
- Add ball, possession or pressing capabilities only after implementing and validating the needed detector and temporal evidence.
- Keep tactical recommendations optional, evidence-linked and coach-controlled; evaluate advice quality separately from event detection.

## Product gates before commercial claims

- Multiple licensed matches and teams, with a genuinely held-out evaluation set.
- Clear coach benefit validated in observed workflows.
- Privacy, retention, access control and support reviewed for the intended deployment.
- Published latency/cost range from representative server conditions.
- Explicitly named limitations and a safe route when analysis is uncertain or unavailable.
