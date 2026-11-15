# Latest production deployment

**Date:** 15 November 2026 (Asia/Karachi)  
**Status:** deployed and verified under the user's explicit approval.  
**Live site:** https://gaffer-tactics.duckdns.org/  
**Analyst desk:** https://gaffer-tactics.duckdns.org/app

## Deployed version

| Item | Value |
|---|---|
| Production image | `gaffer:ui-20261115-061935-f6b77a16a149` (also `gaffer:latest`) |
| Production image ID | `sha256:90861b8146abc09a7d6fd6cf44d7e89d04a3a24a97edbb5c428696fd350f6d30` |
| Image size | 897,438,746 bytes |
| Reviewed source | `postdeploy_ui_20261114T154829Z-f6b77a16a149`, an approved working-tree snapshot, not a Git commit |
| Source archive | `s3://gaffer-demo-221039325928/src/gaffer-postdeploy_ui_20261114T154829Z-f6b77a16a149.tar.gz` |
| Archive SHA-256 | `70749239eea008b8bbf9c5a0f23006df0af9c96233051357373c098c0f77d84b` |
| Source verification | All 225 source files matched the approved manifest before upload and after extraction |
| Frontend verification | All 42 built files match the approved local build; the public index and all 9 JS/CSS responses match their expected hashes |
| Infrastructure | Existing EC2 `i-0ed7553a2ab9a1d16`, `m7i-flex.large`, `ap-southeast-2` |
| Proxy image | Existing `sha256:3067cc4e02c091399edbd5d65f85a3ff4d511574aecadb47f280c3761e68852e` |

This publishes the reviewed coach-focused landing page, five navigation anchors, Explore Gaffer CTA, customer FAQ, recorded demo, report/error refinements and internal monitoring protections. The local review image and independently built EC2 image have different image IDs; their frontend bytes, critical source files and approved configuration were verified directly.

## Deployment procedure

1. Read the prior deployment and verification reports. Compared the current source with the approved archive and confirmed that the old image, prior database backup and active mounts were available.
2. Compared 35 critical CV, AI, tactics, contract and event-store source files with production: unchanged. Compared configuration excluding the approved frontend cache setting: unchanged. Model weights also retained the same hash.
3. Uploaded the approved archive to the existing private bucket. Built natively on EC2 using the existing Dockerfile and the exact Python/Node base-image digests used in review. The build took **35 seconds** while production continued running.
4. Verified the image's 42 frontend hashes, frozen fingerprint and calibration switches. Validated the proxy rules using the existing Caddy binary. An isolated app/proxy pair passed normal, internal-endpoint and forged-header checks before cutover; temporary containers were removed.
5. Tagged the running image for rollback, retained the previous Caddyfile and made a consistent live SQLite backup. Stopped the idle app, refreshed the database backup at that quiescent point and archived the complete persistent output directory.
6. Replaced only the app container and reloaded the reviewed monitoring restrictions into the existing Caddy container. Existing domain, TLS certificates, ports, proxy timeouts, IAM role, assets and EBS mounts were preserved.
7. HTTPS, private diagnostics, database integrity and monitoring restrictions passed after **4 seconds**. Then completed public browser/API checks, promoted `gaffer:latest` and saved the current source under `/opt/gaffer/src`. Previous source remains available with the release.

No new AWS infrastructure, instance resize, IAM edit, security-group edit or DNS change was made. No secret files were read or packaged. No Git staging, commit or push was performed.

## Validation results

| Check actually run | Result |
|---|---|
| Docker state | App `healthy`; Caddy running and serving HTTPS; both restart policies `unless-stopped`; no app host port exposed |
| Public `/`, `/app`, `/api/health` and data APIs | 200; health returns only `{"status":"ok"}` |
| Domain/HTTPS | Existing certificate verified; HTTP domain redirects to HTTPS with 308; legacy plain-IP health remains available |
| Navigation and CTA | Product / How It Works / Features / Demo / FAQ and Explore Gaffer passed |
| Responsive browser walkthrough | Passed at 1440x900, 768x1024 and 390x844: landing, idle desk, setup, upload selection/focus, sample selection, completed review, report, chat shell and not-found recovery; no unexpected console/page errors or horizontal overflow |
| Recorded replay | 12 clips, 11 seek boundaries, 11 playback handoffs, 1x/2x/4x and event reveal at 1085 seconds passed |
| Tactical evidence | Trace/evidence overlays opened and closed at desktop/mobile widths; additional checks waited for video readiness and successful JPEG decoding before final screenshots |
| API error states | Unknown analysis/API route and missing asset returned 404 without tracebacks |
| Video streaming | Both samples and all 12 replay clips returned correct 206 byte ranges: 14 checks passed |
| Internal monitoring | 16 public requests across HTTPS and plain IP, normal and forged forwarded-loopback headers, and trailing-slash variants returned 404. Internal paths are absent from OpenAPI. Container-loopback diagnostics remain available |
| Cache behavior | Public HTML/named files revalidate; hashed JS/CSS use the configured immutable lifetime. The public bundles match the reviewed build |
| Database | Integrity `ok`; original 17 events, one coach decision, three posture attempts, four recommendations and four migrations retained; no schema changes |
| Existing artifacts/results | 165 pre-existing regular files, excluding SQLite database/journal representations checked separately, are byte-for-byte unchanged; no missing files. All 12 stored completed-analysis result endpoints returned 200 |
| Data mutation during browser tests | Assertions confirmed no production write requests; coach alert approval in replay remained session-only |
| Frozen behavior | OpenCV `5.0.0`, fingerprint `ca4ff9bbf7b01c6c`; calibration tiers OFF; CV/AI code, Bedrock settings, model hash and event-store implementation unchanged |
| Bedrock | Zero real calls / $0 inference cost during deployment and smoke checks; instance-role configuration preserved |
| Production logs | No application errors/tracebacks. One local readiness-probe 502 occurred during the four-second app replacement. No ongoing app/proxy errors after startup |

The original and final database dumps, calculated inside Python 3.12 in the app, have the same SHA-256: `03bd10fc9936385e0b4b077a992635549587eff5946f4aac491965cba11769c8`. Quiescent host-side backup/after checks also matched; dump serialization differs between host and container SQLite/Python versions, so hashes are compared within the same environment.

Predeployment test evidence was reused because the approved source did not change: **332 Python tests** passed across two partitions (3 existing NumPy warnings), **53 frontend tests**, lint, ruff and production build passed in the review session. These full suites were not rerun during this deployment; the build, isolated staging checks and live checks above were run now.

## Backup and rollback

Release directory: `/opt/gaffer/releases/ui-20261115-061935-f6b77a16a149/`.

- Immediate previous image: `gaffer:rollback-ui-20261115-061935-f6b77a16a149`, ID `sha256:2d0c7075eac1d5f5bbaddb77e64975022bb5f9bd92831a9193b3e4044dd7e481`.
- Fresh consistent SQLite backup: `backups/events.sqlite3` (184,320 bytes).
- Full pre-cutover output backup: `backups/outputs-before.tar.gz` (9,846,551 bytes).
- Previous reverse-proxy file: `backups/Caddyfile.previous`.
- Previous source: `previous-source/` and `source-before-promotion/`.
- Earlier deployment's database backup and older rollback image were also retained.

The backup directory and rollback scripts are restricted to the operator. Use the existing IAM/SSM connection to run, as root:

```sh
sh /opt/gaffer/releases/ui-20261115-061935-f6b77a16a149/rollback.sh
```

The script restores the previous app image, proxy configuration and source, retains the persistent data mounts, and verifies HTTPS health. It does not overwrite the database with an old backup, so later coach activity is preserved. Shell syntax and rollback image availability were verified. **Rollback was not invoked**, because deployment checks passed. The older release has its earlier public diagnostic behavior; recheck monitoring restrictions if it is restored.

## Production screenshots

| View | Desktop | Mobile |
|---|---|---|
| Landing | [1440px](screenshots/deployment-2026-11-15/after-landing-1440.png) | [390px](screenshots/deployment-2026-11-15/after-landing-390.png) |
| Analyst desk | [1440px](screenshots/deployment-2026-11-15/after-app-1440.png) | [390px](screenshots/deployment-2026-11-15/after-app-390.png) |
| Completed review, media loaded | [1440px](screenshots/deployment-2026-11-15/after-review-1440.png) | [390px](screenshots/deployment-2026-11-15/after-review-390.png) |
| Verification detail | [1440px](screenshots/deployment-2026-11-15/after-checks-1440.png) | [390px](screenshots/deployment-2026-11-15/after-checks-390.png) |
| Evidence image | [1440px](screenshots/deployment-2026-11-15/after-evidence-1440.png) | [390px](screenshots/deployment-2026-11-15/after-evidence-390.png) |

Initial review captures were taken before media completed loading; final review/evidence captures were replaced after explicit readiness checks. Raw deployment scripts, hashes, SSM results and additional screenshots are in `outputs/deploy_approved_20261115_061935Z/`.

## Remaining issues and limits

- The observed readiness interruption was four seconds; an active request could fail briefly during app replacement. The existing Caddy/TLS process stayed running.
- Existing tabs may need a refresh to load the new UI. No service worker was added.
- No new full upload processing, real Bedrock inference, reboot exercise, formal accessibility audit or physical Safari/iOS device test was performed. Upload selection and saved results were checked without generating new production analyses.
- Existing product limits remain: recorded footage, limited real-match validation, possible missed changes, conditional heuristic advice and no ball/possession/pressing evidence or private club accounts.
- Approximately 23 GB remains free on the existing volume. Current operating costs continue; this deployment added no new AWS resource.

There is no remaining deployment blocker from the checks above.
