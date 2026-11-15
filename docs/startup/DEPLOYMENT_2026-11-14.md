# Startup UI deployment: 14 November 2026

The user explicitly authorized deploying the current startup UI to the existing AWS setup. No Git staging, commit or push was performed. The uncommitted application files were included in a source snapshot with per-file SHA-256 hashes; this deployment is not represented as a committed revision.

- Public site: https://gaffer-tactics.duckdns.org/
- Analyst desk: https://gaffer-tactics.duckdns.org/app
- EC2: existing `i-0ed7553a2ab9a1d16`, `m7i-flex.large`, `ap-southeast-2`.
- Image: `gaffer:startup_20261114T151853Z-9262acbc7897` (also tagged `gaffer:latest`).
- EC2 image ID: `sha256:2d0c7075eac1d5f5bbaddb77e64975022bb5f9bd92831a9193b3e4044dd7e481`; 897,524,619 bytes.
- Source: `s3://gaffer-demo-221039325928/src/gaffer-startup_20261114T151853Z-9262acbc7897.tar.gz`.
- Archive SHA-256: `06c8ef3705c77c904c10c0a485902df49e42ee5ffc6dee5e5eb7cb7e8d9abfa8`; 226 application/build files, 1,537,622 bytes.

## Procedure and recovery

1. Checked the existing instance, SSM connection, disk and idle worker; the old app was healthy and no analysis was running.
2. Built the existing multistage Dockerfile locally; tested `/`, `/app` and `/api/health` in a temporary local container. Removed that temporary container after the checks.
3. Uploaded the current build inputs to the existing private S3 bucket. The allowlist omitted credentials, `.env` files, Git, local dependencies, outputs and large media. No credential files were read.
4. Verified archive and per-file hashes on EC2, then built and checked the new image before replacing the app. Native EC2 build took 42 seconds.
5. Backed up SQLite consistently using its backup API and retained the old image as `gaffer:rollback-startup_20261114T151853Z-9262acbc7897`.
6. Replaced only `gaffer`, retaining Caddy, its certificates, Docker network and persistent output/assets mounts. The front-door health check passed 4 seconds after the switch began. The switch script automatically restores the old image if its startup checks fail; this was not needed.
7. Promoted the checked image to `latest` and saved the source under `/opt/gaffer/releases/startup_20261114T151853Z-9262acbc7897/` and `/opt/gaffer/src`.

SQLite backup: `/opt/gaffer/outputs/deploy_backups/startup_20261114T151853Z-9262acbc7897/events.sqlite3`. Before and after SQL dump hashes were identical: `03bd10fc9936385e0b4b077a992635549587eff5946f4aac491965cba11769c8`. Integrity check returned `ok`; 17 event records, one coach decision, three posture attempts, four recommendations and four schema migrations were preserved.

## Checks

| Check | Result |
|---|---|
| Local Docker build and HTTP smoke | Passed |
| EC2 container | Running, Docker health `healthy`, restart policy `unless-stopped` |
| Public HTTPS `/`, `/app`, `/api/health`, `/api/runtime` | 200 |
| HTTP domain redirect | 308 to the equivalent HTTPS path |
| Legacy plain IP health route | 200 |
| Sample and replay streaming | All 14 byte-range checks returned 206: two samples and 12 replay clips |
| Stored demo events and sample catalogue | Identical to the predeployment API snapshots |
| Public desktop/mobile UI | 1440x900 and 390x844: no horizontal overflow or page errors; screenshots captured and visually reviewed |
| Full public replay walkthrough | Passed: 12 clips, 11 seek boundaries and playback handoffs, 1x/2x/4x, event reveal at 1085 seconds, keyboard setup and session-only coach approval. Zero write requests. |
| OpenCV / frozen rules | `5.0.0` / `ca4ff9bbf7b01c6c` |
| Calibration tiers | Both OFF |
| Bedrock | Zero calls and zero inference cost during deployment/checks; IAM role remains configured |
| Startup / assets / logs | Startup completed; 27 existing assets reused, zero downloaded; CloudWatch app stream receiving events |

No new AWS resource, instance resize, IAM edit, security-group edit or DNS change was needed. This uses the existing paid/credit-consuming instance; the older documented operating estimate is approximately $3.10/day plus Bedrock, not a fresh price or credit-balance check. The new source archive is about 1.54 MB. There is 24 GB free disk after the build; the previous image and source are retained for recovery.

Local deployment evidence and scripts: `outputs/deploy_startup_20261114T151853Z/`. The source manifest and before/after API snapshots are stored there; browser screenshots include `landing-1440.png`, `landing-390.png`, `desk-1440.png`, `desk-390.png` and `production-mobile-replay.png`.

The public replay check reused the existing test with the production event's saved `balanced` objective and no available roles, preserving its recommendation context. The first unbounded browser run was interrupted after waiting without a result. The rerun added explicit browser timeouts and step logging and passed; no product change or mock was needed. The streamed byte-range check initially used an incorrect non-zero-padded clip URL in the scratch verifier; corrected IDs such as `0900-0930` passed.

No new full upload analysis, live Bedrock inference, server reboot test, formal accessibility audit or unfamiliar-user walkthrough was performed for this deployment. The existing one-match, recorded-footage and heuristic-advice limitations continue to apply.
