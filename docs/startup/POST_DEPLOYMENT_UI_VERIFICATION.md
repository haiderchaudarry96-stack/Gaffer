# Post-deployment verification and UI refinement

**Date:** 14 November 2026  
**Branch:** `feature/startup-ui-phase1`  
**Deployment status:** this report records the 14 November review. The user subsequently approved deployment, completed on **15 November 2026**. See [DEPLOYMENT_LATEST.md](DEPLOYMENT_LATEST.md) for the current production image and checks. No commit or push was made.

## Production baseline observed on 14 November

This session used read-only SSM inspection, public HTTP requests and a fresh Chromium browser. It did not rely on the earlier deployment report as proof.

| Item | Observed value |
|---|---|
| App image tag | `gaffer:startup_20261114T151853Z-9262acbc7897` |
| App image ID | `sha256:2d0c7075eac1d5f5bbaddb77e64975022bb5f9bd92831a9193b3e4044dd7e481` |
| Proxy image | `public.ecr.aws/docker/library/caddy:2` |
| Proxy image ID | `sha256:3067cc4e02c091399edbd5d65f85a3ff4d511574aecadb47f280c3761e68852e` |
| Containers | Both running; app healthy; both use `unless-stopped` |
| Published ports | Caddy 80/443; app publishes no host port |
| Persistence | Existing outputs, media/model assets and Caddy certificate mounts retained |
| Active configuration | Sydney region, proxy trust enabled, existing asset bucket; config file matched local baseline before refinement |
| Rollback image | Earlier rollback image exists: `sha256:65494fa4814a2c6fc25d18ac5c3d1cfd51f06c8893c798d851ac36922574cff9` |
| Frozen rules | `ca4ff9bbf7b01c6c`; both calibration tiers OFF |

All **42 files** in the locally built frontend matched the running container byte for byte before changes. The public HTML matched the container, and all **9 JS/CSS assets** fetched over HTTPS matched its hashes. Expected Phase 1 labels, source-scoped evaluation cards, recorded-analysis entry and coaching setup were present. The original deployment succeeded; its design remained too technical for the requested product direction.

Selected full SHA-256 values:

| File | Production baseline | Local refinement |
|---|---|---|
| `index.html` | `3f680bf5b5070790902c88e692ecc43e6636ee1d0739bb0cd70936889ec62a93` | `10fb5873a00033534bf698d9ffeea1fe22584d1c7cf365e33d0c0b77e4b081e4` |
| Landing body | `LandingBody-BWW1bKpO.js`: `399d481cbe43c920c39aee7765443f1bd07ae76551583c05940055232e4114a8` | `LandingBody-DA4HG0p_.js`: `ddf8b4c6c453e1c3a7fc3d8a371f45198242bab1066c1b0c325e6c4e922b827d` |
| Entry bundle | `index-nYGnsUQO.js`: `0958e652e5ab7dd4ed9bf56af22c9db743722f721f70bbbd9d4eece277e31325` | `index-CJhDbgp_.js`: `5bb139176906bc065a6a70aea241adfc08ee3c85be29b56341400415b12f29cb` |

Raw inspection, active proxy configuration, complete hashes and browser cache evidence: `outputs/postdeploy_ui_20261114T154829Z/deployment-inspection.json` and `browser-baseline.json`.

The live SQLite database and the retained deployment backup were also inspected read-only. Both passed `integrity_check`, both contain 17 event records, one coach decision, three posture attempts and four recommendations, and their SQL dump hashes match exactly: `03bd10fc9936385e0b4b077a992635549587eff5946f4aac491965cba11769c8`. This independently verifies the earlier preservation claim. Evidence: `database-verification.json` in the same output folder.

## Cache findings

No service-worker registration or Cache Storage entries were found in the fresh/warm production browser. Reloading reused 28 cached responses, including static assets, while the HTML was fetched again. Production HTML had no explicit `Cache-Control` policy. There was no evidence that a service worker or wrong asset version caused the technical UI. An individual visitor's old browser profile was not inspected, so this does not prove every existing tab is current.

The local candidate explicitly revalidates HTML and named public files with `Cache-Control: no-cache`. Vite's content-hashed assets use a configured immutable lifetime (`api.web_cache.asset_max_age_s`). Missing asset URLs now return 404 instead of the HTML shell. No service worker was added. A final parity check caught an older local CSS build after documentation edits affected the Tailwind scan; rebuilding the local distribution resolved it, and all 42 files then matched the final Docker image.

## What was missing and what changed

| Previous presentation | Local refinement |
|---|---|
| Evaluation and technology dominated the public story | Product benefits, coaching workflow and six descriptions of existing capabilities |
| Evidence/Evaluation/Technology navigation | Product / How It Works / Features / Demo / FAQ; every anchor exercised at desktop, tablet and mobile sizes |
| Long analyst-desk CTA | Consistent **Explore Gaffer** CTA |
| Raw OpenCV function and cloud service cards | Engineering material in `PRODUCT_TECHNICAL_NOTES.md` and the existing technical reports |
| Instance, region/zone, model counters and uptime displayed publicly | Monitoring card and its frontend client removed; public liveness minimized; detailed endpoints restricted to loopback and blocked by Caddy |
| Limitations resembled an evaluation failure list | Practical footage guide and customer FAQ; uncertainty, limited testing, no live camera/ball/possession/pressing and coach responsibility remain explicit |
| Embedded screenshot used old control labels | Product screenshot and social preview regenerated from the current UI/copy |
| A button said Generate while opening a saved report | **View report**, with consistent accessible name on mobile and desktop |
| Template-generation history led the coach report | Concise report introduction; source-check/template explanation preserved under **About this report** |
| Error descriptions used small monospace text | Readable body text with recovery actions retained; not-found screen has a page heading |

No customer adoption, testimonials, accuracy guarantee, live-camera support or automatic tactical decision feature was invented. Formation verification, posture, conditional advice and coach responses remain separate. CV/perception, tactics, model selection, frozen agent settings and data contracts are unchanged. Configuration changes are limited to the frontend asset cache lifetime under `api:`.

## Monitoring protection

The local candidate makes public `/api/health` return only `{"status":"ok"}`. `/api/runtime` and `/api/internal/health` require container loopback, are omitted from OpenAPI and are blocked by the public Caddy routing rules. Operators retain access through IAM-protected SSM and `docker exec`; CloudWatch remains internal. No public monitoring/admin screen or browser credential was added.

A real local Docker/Caddy pair passed 10 routing checks, including normal traffic and forged `X-Forwarded-For: 127.0.0.1` / `X-Real-IP: ::1`. The internal paths returned 404; public liveness and both app routes returned 200; container-loopback diagnostics still returned the frozen fingerprint. This tested the candidate proxy rules with only the test address/upstream substituted. Production still had the old detailed endpoints at this review; the protections were subsequently deployed and verified on 15 November.

## Actual validation

| Command / check | Result |
|---|---|
| `npm test` | 8 files, **53 tests passed**; the obsolete public-runtime adapter/card tests were retired with that client |
| `npm run lint` | Passed |
| `VITE_API_URL=/; npm run build` | Passed; 2,417 transformed modules |
| `ruff check .` | Passed |
| `pytest -q -o addopts='' tests/test_api.py tests/test_server_safety.py tests/test_teamtrack_replay.py` | **76 passed**, 3 existing NumPy all-NaN warnings, 725.54 seconds |
| Focused health/monitoring/cache/fingerprint checks after final changes | **6 passed**, 43 deselected |
| `pytest -q -o addopts='' --ignore=tests/test_api.py --ignore=tests/test_server_safety.py --ignore=tests/test_teamtrack_replay.py` | **256 passed** in 1293.14 seconds. Together with the 76 API/safety/replay cases, all **332 Python tests** passed across the two partitions; the final six-check recheck is not counted again |
| `node scripts/verify-product-ui.mjs` | Passed at **1440x900, 768x1024 and 390x844**: five navigation links, CTA, keyboard FAQ/setup, selected upload focus/visibility, sample selection, completed analysis, report, chat shell and not-found return |
| `node scripts/verify-upload-states.mjs` | Passed at 1440x900 and 390x844: pitch confirmation/adjustment, one server ETA plus separate agent budget, uploaded results and recoverable busy error. These responses are explicitly mocked UI fixtures |
| Local connected `e2e-teamtrack-replay.mjs` | Passed: 12 clips, 11 seek boundaries/handoffs, 1x/2x/4x and event reveal at 1085 seconds |
| Trace and evidence overlays | Passed at 1440px and 390px: opened, captured and closed with Escape; no page errors |
| Fresh read-only public replay walkthrough | Passed: 12 clips, 11 seek boundaries/handoffs, 1x/2x/4x, event reveal at 1085 seconds; no write requests |
| Console / layout | No console/page errors or horizontal overflow in the non-mocked product walkthroughs; expected error fixtures are identified separately |
| Docker candidate / Caddy | Multistage image built; proxy configuration valid; private/public routing checks passed |
| Candidate image frontend | All 42 files match the local build; fingerprint unchanged |
| Bedrock | No real model calls made |

Local image tag: `gaffer:ui-review-20261114`. Final candidate image ID: `sha256:200a61cf0ecbe01d7337f85c2cdc15bd0568634bb45a4e295656ec067da3a40e`. This image is a local review artifact, not an EC2 deployment. The prepared source archive is `outputs/postdeploy_ui_20261114T154829Z/gaffer-postdeploy_ui_20261114T154829Z-f6b77a16a149.tar.gz` (225 files; SHA-256 `70749239eea008b8bbf9c5a0f23006df0af9c96233051357373c098c0f77d84b`). It has not been uploaded to S3.

The combined local preview is available at `http://127.0.0.1:8017/` with Bedrock disabled. Temporary Docker proxy/app test containers and their test network were removed; the reviewed image is retained locally.

## Screenshots and comparison

Production baseline captures were made before editing. Candidate captures use the connected local app; files prefixed `fixture-` use mocked upload responses. All are in `docs/startup/screenshots/post-deployment/`.

| Screen | Desktop | Mobile |
|---|---|---|
| Landing before | [1440px](screenshots/post-deployment/before-landing-1440.png) | [390px](screenshots/post-deployment/before-landing-390.png) |
| Landing after | [1440px](screenshots/post-deployment/after-landing-1440.png) | [390px](screenshots/post-deployment/after-landing-390.png) |
| Hero after | [1440px](screenshots/post-deployment/after-hero-1440.png) | [390px](screenshots/post-deployment/after-hero-390.png) |
| App before | [1440px](screenshots/post-deployment/before-app-1440.png) | [390px](screenshots/post-deployment/before-app-390.png) |
| App after | [1440px](screenshots/post-deployment/after-app-1440.png) | [390px](screenshots/post-deployment/after-app-390.png) |
| Recorded setup | [1440px](screenshots/post-deployment/after-setup-1440.png) | [390px](screenshots/post-deployment/after-setup-390.png) |
| Selected upload | [1440px](screenshots/post-deployment/after-selected-file-1440.png) | [390px](screenshots/post-deployment/after-selected-file-390.png) |
| Sample selection | [1440px](screenshots/post-deployment/after-sample-selected-1440.png) | [390px](screenshots/post-deployment/after-sample-selected-390.png) |
| Completed analysis | [1440px](screenshots/post-deployment/after-review-1440.png) | [390px](screenshots/post-deployment/after-review-390.png) |
| Coach report | [1440px](screenshots/post-deployment/after-report-1440.png) | [390px](screenshots/post-deployment/after-report-390.png) |
| Chat shell | [1440px](screenshots/post-deployment/after-chat-1440.png) | [390px](screenshots/post-deployment/after-chat-390.png) |
| Verification details | [1440px](screenshots/post-deployment/after-checks-1440.png) | [390px](screenshots/post-deployment/after-checks-390.png) |
| Evidence image | [1440px](screenshots/post-deployment/after-evidence-1440.png) | [390px](screenshots/post-deployment/after-evidence-390.png) |
| Pitch adjustment fixture | [1440px](screenshots/post-deployment/fixture-pitch-adjust-1440.png) | [390px](screenshots/post-deployment/fixture-pitch-adjust-390.png) |
| Progress fixture | [1440px](screenshots/post-deployment/fixture-progress-1440.png) | [390px](screenshots/post-deployment/fixture-progress-390.png) |
| Upload result fixture | [1440px](screenshots/post-deployment/fixture-upload-result-1440.png) | [390px](screenshots/post-deployment/fixture-upload-result-390.png) |
| Error fixture | [1440px](screenshots/post-deployment/fixture-upload-error-1440.png) | [390px](screenshots/post-deployment/fixture-upload-error-390.png) |

Tablet captures and not-found screenshots are in the same folder. The before/after comparison preserves Gaffer's lime, pitch colours, typography and analyst desk while replacing the public engineering presentation with an actual review workflow.

## Remaining limitations and deployment approval

- This remains an early product with limited real-footage validation. Some changes are missed; role advice is a conservative heuristic. No model behavior was improved by this UI work.
- No unfamiliar-user session, screen-reader audit, formal WCAG certification or Safari/iOS device test was performed. Browser coverage is Chromium at the documented sizes, primarily with reduced motion.
- Upload fixture screenshots do not claim a new production video-processing run. The real generated-video pipeline is exercised by the Python API regression suite; live inference and a new full TeamTrack upload were not run.
- There are no private club accounts. Footage handling and retained results are disclosed in the FAQ; access-control work for customer accounts is outside this task.
- Existing browser tabs may keep their already-loaded code until refreshed. The candidate improves future cache behavior without adding a service worker.
- No production deploy, S3 source upload, production database write or production container restart was performed during the 14 November review. The separate approved 15 November deployment is recorded in [DEPLOYMENT_LATEST.md](DEPLOYMENT_LATEST.md).

After approval: snapshot the reviewed source, verify it, back up the existing event DB, retain the current image and Caddyfile for rollback, replace the app container and reload the tested Caddy rules. Then verify the private diagnostics through container loopback and public routes through HTTPS; compare persisted records and repeat the public browser smoke checks. No new AWS infrastructure is required.
