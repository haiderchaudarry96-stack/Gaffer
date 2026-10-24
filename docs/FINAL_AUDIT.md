# Final audit (24 Oct 2026)

Written by the overnight documentation session; updated the same morning (logo applied, `coarse_to_fine` re-checked on the demo window and `eval2`, TeamTrack sample re-encoded). Everything here was checked on 24 Oct against the files named; nothing is assumed. "Unverified" means exactly that.

## 0. Things only the author can do or confirm

1. **The repository is private.** Devpost judges must be able to see the code: **make the repository public, or give the judges access, before submitting.** Nothing in this session changed that. README, DEVPOST and the report link to files by relative path, which only works once the repo is readable (`TBD-REPO`).
2. **Author name and school.** The README footer says "Haider Sultan · FAST-NUCES, Pakistan"; `docs/DEMO_SCRIPT.md` section 1 uses it, and `git config user.name` agrees. The account e-mail on this machine carries a different name, so please confirm the spelling you want said in the video.
3. **Placeholders** (section 7): only the demo video link (`TBD-VIDEO`) and the repository link (`TBD-REPO`) are left. `TBD-URL` and `TBD-EC2` were filled on 24 Oct after the deploy.
4. **Deployed on 24 Oct (afternoon)** at revision `13c69e4`: https://gaffer-tactics.duckdns.org/ (Let's Encrypt, Caddy; the plain-http IP link still works), both samples in S3, the new logo, the 32 MB TeamTrack sample, the A4 speed-up. Not yet on the server: the social preview image and its `<meta>` tags (`og-image.png`, `web/index.html`; they need one more commit and redeploy). The two alerts from the 6-minute test upload (`alr_up_de899ff9f46a_evt_001` / `_002`) are pending in the live alert store.
5. **Budget.** `gaffer-budget` was still $10/month at the last record (22 Oct); the server alone crosses it in about 3 days. Raising it to $40 is a console action (`deploy/DEPLOY_AWS.md`).
6. The AWS **account id** (221039325928) appears in docs through the bucket name. It is an identifier, not a credential, but it will be public with the repo.

## 1. Secrets scan

Scanned every tracked file and every untracked, not-ignored file (468 files; images, video and lockfiles skipped) for AWS access key ids (`AKIA…`/`ASIA…`), `aws_secret_access_key` / `aws_access_key_id` assignments, PEM private keys, GitHub / OpenAI / Slack / Google key patterns and `secret_key = "…"` assignments.

- **Hits:** only `tests/test_agent.py:841` and `tests/test_bedrock_client.py:45`, the literal dummy value `"testing"` used to build a fake boto3 client in mocked tests.
- `.env` is not tracked (`.gitignore`); `.env.example` holds a profile name and a region only. No `*.pem`, `*.key`, credentials file or SQLite database is tracked. `~/.aws` was never read.
- The Zenodo annotation password in `docs/DATA_SOURCES.md` and `data/README.md` (`10.5281/zenodo.14867794`) is published in the Zenodo record's description by the dataset authors; it is not ours.
- Not scanned: git history. Run a secrets scanner over `git log -p` before making the repo public if you want certainty.

## 2. Licences

No AGPL, no GPL runtime dependency and no Ultralytics code or weights (`grep -iE "ultralytics|agpl|gpl" requirements.lock` finds nothing). The lists below are read from the installed package metadata of the pinned versions on this machine. Entries whose metadata is unclear are marked **unverified**.

### Python (`requirements.lock`, 54 packages)

| package | version | licence (metadata) |
|---|---|---|
| annotated-doc | 0.0.5 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.15.1 | MIT |
| av | 19.0.1 | BSD-3-Clause |
| boto3 | 1.43.110 | Apache-2.0 |
| botocore | 1.43.110 | Apache-2.0 |
| certifi | 2026.7.22 | MPL-2.0 |
| charset-normalizer | 3.5.2 | MIT |
| click | 8.5.0 | BSD-3-Clause |
| colorama | 0.4.6 | BSD License |
| contourpy | 1.4.0 | BSD-3-Clause |
| cycler | 0.12.1 | BSD-3-Clause *(metadata gives the licence text only: unverified)* |
| defusedxml | 0.7.1 | PSF-2.0 |
| fastapi | 0.143.3 | MIT |
| fonttools | 4.66.1 | MIT |
| h11 | 0.16.0 | MIT |
| httpcore2 | 2.13.0 | BSD-3-Clause |
| httpx2 | 2.13.0 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| iniconfig | 2.3.1 | MIT |
| jmespath | 1.1.0 | MIT |
| kiwisolver | 1.5.1 | BSD-3-Clause *(metadata unclear: unverified)* |
| matplotlib | 3.11.2 | PSF-based (matplotlib licence) |
| numpy | 2.5.3 | BSD-3-Clause (wheels also bundle 0BSD, MIT, Zlib, CC0 parts) |
| opencv-contrib-python | 5.0.0.93 | Apache 2.0 |
| opentelemetry-api | 1.45.1 | Apache-2.0 |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pandas | 3.0.6 | BSD 3-Clause License |
| pillow | 12.3.0 | MIT-CMU |
| pluggy | 1.6.0 | MIT |
| pydantic | 2.14.0 | MIT |
| pydantic_core | 2.50.0 | MIT |
| pyDeprecate | 0.13.0 | Apache-2.0 |
| Pygments | 2.21.0 | BSD-2-Clause |
| pyparsing | 3.3.3 | MIT |
| pytest | 9.1.1 | MIT |
| python-dateutil | 2.9.0.post0 | Apache-2.0 / BSD-3-Clause dual *(metadata says "Dual License": unverified)* |
| python-dotenv | 1.2.4 | BSD-3-Clause |
| python-multipart | 0.0.32 | Apache-2.0 |
| PyYAML | 6.0.3 | MIT |
| requests | 2.34.2 | Apache-2.0 |
| ruff | 0.16.10 | MIT |
| s3transfer | 0.19.2 | Apache License 2.0 |
| scipy | 1.18.1 | BSD License |
| six | 1.17.0 | MIT |
| starlette | 1.8.0 | BSD-3-Clause |
| supervision | 0.30.9 | MIT |
| tqdm | 4.70.1 | MPL-2.0 AND MIT |
| truststore | 0.10.5 | MIT |
| typing-inspection | 0.4.4 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| tzdata | 2026.5 | Apache-2.0 |
| urllib3 | 2.8.0 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |

PyAV (`av`) wheels bundle FFmpeg under LGPL (dynamically linked, unmodified). `make_sample_clip.py --codec x264` uses the libx264 encoder inside the PyAV wheel on the author's machine to produce a sample file; the encoder is not shipped, only the resulting MP4.

### Web (`web/package.json`, direct dependencies; read from `node_modules/*/package.json`)

| package | version | licence |
|---|---|---|
| @fontsource-variable/inter | 5.3.0 | OFL-1.1 |
| @fontsource-variable/jetbrains-mono | 5.3.0 | OFL-1.1 |
| @fontsource-variable/space-grotesk | 5.3.0 | OFL-1.1 |
| lenis | 1.3.27 | MIT |
| lucide-react | 1.59.0 | ISC |
| motion | 14.3.0 | MIT |
| react | 19.3.1 | MIT |
| react-dom | 19.3.1 | MIT |
| react-router-dom | 7.18.4 | MIT |
| @eslint/js | 9.39.5 | MIT |
| @tailwindcss/vite | 4.3.3 | MIT |
| @types/node | 24.19.2 | MIT |
| @types/react | 19.3.0 | MIT |
| @types/react-dom | 19.3.0 | MIT |
| @vitejs/plugin-react | 6.1.2 | MIT |
| eslint | 9.39.5 | MIT |
| eslint-plugin-jsx-a11y | 6.10.2 | MIT |
| eslint-plugin-react-hooks | 7.1.1 | MIT |
| eslint-plugin-react-refresh | 0.5.7 | MIT |
| globals | 17.13.0 | MIT |
| playwright-core | 1.64.1 | Apache-2.0 |
| tailwindcss | 4.3.3 | MIT |
| typescript | 6.0.3 | Apache-2.0 |
| typescript-eslint | 8.71.2 | MIT |
| vite | 8.3.4 | MIT |
| vitest | 5.0.5 | MIT |

### Data and models

TeamTrack (MIT), the Zenodo clip (CC BY 4.0, credit shown on the upload page and in the README), YOLOX-S ONNX from the OpenCV Model Zoo (Apache 2.0, not in the repo), Amazon Nova 2 Lite / Micro (AWS terms). Full record: `docs/DATA_SOURCES.md`.

## 3. Links

Checked with `curl -L` on 24 Oct:

| link | result |
|---|---|
| https://arxiv.org/abs/2404.13868 | 200 |
| https://doi.org/10.5281/zenodo.14867795 and https://zenodo.org/records/14867795 | 200 |
| https://github.com/AtomScott/TeamTrack | 200 |
| https://github.com/opencv/opencv_zoo (and the YOLOX model folder) | 200 |
| https://www.kaggle.com/datasets/atomscott/teamtrack | 200 (the page loads; downloading needs a Kaggle login) |
| https://opencv26.devpost.com | 200 |
| https://gaffer-tactics.duckdns.org/, `/app`, `/api/health` | 200, certificate verified (Let's Encrypt, valid to 22 Jan 2027), checked 24 Oct after the deploy |
| http://gaffer-tactics.duckdns.org/app | 308 to https |
| http://13.210.196.109/ and `/api/health` | 200 over plain http (fallback link) |
| https://www.linkedin.com/in/haider-sultan-32209640a | **999 (LinkedIn blocks scripts): unverified** |
| demo video, final public URL, repository | **placeholders, not yet existing** |

## 4. Checks run

Run on 24 Oct (re-run in the morning after the logo, `scripts/` and doc changes; no `src/` change since the overnight run; log: `outputs/pytest_final_24oct_morning.log`, overnight log `outputs/pytest_final_24oct.log`):

| check | result |
|---|---|
| `pytest -o addopts="" -p no:cacheprovider` (LLM mocked, no Bedrock call) | **304 passed**, 3 warnings (the known NumPy all-NaN warnings in `test_pipeline_failure_is_coach_readable`), 850.6 s (14 min: the laptop was busy; overnight 386 s) |
| `ruff check .` | All checks passed |
| `cd web; npm test` | 7 files, **48 passed** |
| `cd web; npm run lint` (full) | clean (the `window` no-undef in `e2e-integrate.mjs` is fixed) |
| `cd web; $env:VITE_API_URL="/"; npm run build` | built |
| rules fingerprint (`gaffer.api.jobs.rules_fingerprint`) | `ca4ff9bbf7b01c6c`, unchanged |
| `git diff --check` | only LF/CRLF notes, no whitespace errors |
| `scripts/audit_numbers.py` | 204 claims, 0 not ok (5.1) |

New tests this session: `tests/test_resolution.py` (4), `test_two_samples_list_download_and_pick_by_id`, a resolution assertion in the upload end-to-end test, `test_drift_coarse_to_fine_…`, and 1 web test (sample list and result `resolution`).


## 5. Every number in README / TECHNICAL_REPORT / DEVPOST against its source

### 5.1 Read from the JSON source by `scripts/audit_numbers.py` (204 claims, 0 not ok)

Re-run with `py scriptsudit_numbers.py` (writes `outputs/final_audit_numbers.md`). 24 Oct: 150 → 182 claims in the morning (demo-window upload re-check, `eval2` with `coarse_to_fine`, sample re-encode), → 204 after the deploy (EC2 sample timings and the EC2 6-minute upload).

| used in | claim | stated | source | source says | check |
|---|---|---|---|---|---|
| README, REPORT §5C, DEVPOST | one-shot real changes alerted | 34 | `outputs/eval_agent_final.json` `arms/oneshot/summary/alerted_hits` | 34.0 | ok |
| README, REPORT §5C, DEVPOST | one-shot false alerts | 34 | `outputs/eval_agent_final.json` `arms/oneshot/summary/false_alerts` | 34.0 | ok |
| README, REPORT §5C, DEVPOST | rules real changes alerted | 32 | `outputs/eval_agent_final.json` `arms/rules/summary/alerted_hits` | 32.0 | ok |
| README, REPORT §5C, DEVPOST | rules false alerts | 9 | `outputs/eval_agent_final.json` `arms/rules/summary/false_alerts` | 9.0 | ok |
| README, REPORT §5C, DEVPOST | agent real changes alerted | 32 | `outputs/eval_agent_final.json` `arms/llm/summary/alerted_hits` | 32.0 | ok |
| README, REPORT §5C, DEVPOST | agent false alerts | 9 | `outputs/eval_agent_final.json` `arms/llm/summary/false_alerts` | 9.0 | ok |
| REPORT §5C | true changes | 38 | `outputs/eval_agent_final.json` `arms/rules/summary/true_changes` | 38.0 | ok |
| REPORT §5C | candidates | 68 | `outputs/eval_agent_final.json` `arms/rules/summary/candidates` | 68.0 | ok |
| REPORT §5C | rules mean alert delay s | 105 | `outputs/eval_agent_final.json` `arms/rules/summary/mean_alert_delay_s` | 105.0 | ok |
| REPORT §5C | one-shot mean alert delay s | 42 | `outputs/eval_agent_final.json` `arms/oneshot/summary/mean_alert_delay_s` | 42.0 | ok |
| REPORT §5C | rejected real changes (rules) | 2 | `outputs/eval_agent_final.json` `arms/rules/summary/rejected_hits` | 2.0 | ok |
| REPORT §5C, DEVPOST | LLM calls | 195 | `outputs/eval_agent_final.json` `llm/llm_calls` | 195.0 | ok |
| REPORT §5C | LLM calls per candidate | 2.9 | `outputs/eval_agent_final.json` `llm/llm_calls_per_candidate` | 2.9 | ok |
| REPORT §5C, DEVPOST | Bedrock cost per match USD | 0.021 | `outputs/eval_agent_final.json` `llm/mean_cost_per_match` | 0.021 | ok |
| REPORT §5C | Bedrock total USD | 0.21 | `outputs/eval_agent_final.json` `llm/cost_usd` | 0.21 | ok |
| REPORT §5C, DEVPOST | decisions equal to rules (of 68) | 68 | `outputs/eval_agent_final.json` `llm/agreement_with_rules` | 68.0 | ok |
| REPORT §5C | guard blocks | 0 | `outputs/eval_agent_final.json` `llm/guard_blocks` | 0.0 | ok |
| REPORT §7.1 | formation accuracy when confident, % | 97.7 | `outputs/eval_synthetic_heldout2.json` `all/formation/overall/accuracy_when_confident` | 97.7 | ok |
| REPORT §7.1 | full view when confident, % | 97.6 | `outputs/eval_synthetic_heldout2.json` `all/formation/full_view/accuracy_when_confident` | 97.6 | ok |
| REPORT §7.1 | broadcast window when confident, % | 98 | `outputs/eval_synthetic_heldout2.json` `all/formation/broadcast/accuracy_when_confident` | 98.0 | ok |
| REPORT §7.1 | strict accuracy, % | 77.4 | `outputs/eval_synthetic_heldout2.json` `all/formation/overall/accuracy_strict` | 77.4 | ok |
| REPORT §7.1 | true changes | 38 | `outputs/eval_synthetic_heldout2.json` `all/changes/true_changes` | 38.0 | ok |
| REPORT §7.1 | hits | 34 | `outputs/eval_synthetic_heldout2.json` `all/changes/hits` | 34.0 | ok |
| REPORT §7.1 | misses | 4 | `outputs/eval_synthetic_heldout2.json` `all/changes/misses` | 4.0 | ok |
| REPORT §7.1 | false positives | 34 | `outputs/eval_synthetic_heldout2.json` `all/changes/false_positives` | 34.0 | ok |
| REPORT §7.1 | mean detection delay s | 42 | `outputs/eval_synthetic_heldout2.json` `all/changes/mean_detection_delay_s` | 42.0 | ok |
| REPORT §7.1 | max detection delay s | 125 | `outputs/eval_synthetic_heldout2.json` `all/changes/max_detection_delay_s` | 125.0 | ok |
| REPORT §7.1 | new formation right | 31 | `outputs/eval_synthetic_heldout2.json` `all/changes/hits_with_correct_new_formation` | 31.0 | ok |
| REPORT §7.1 | timeline max KB | 14 | `outputs/eval_synthetic_heldout2.json` `timeline_bytes/max` | 14.0 | ok |
| REPORT §7.1 | timeline mean KB | 6.3 | `outputs/eval_synthetic_heldout2.json` `timeline_bytes/mean` | 6.3 | ok |
| README, REPORT §7.2 | eval F1 at 1 m raw | 0.918 | `outputs/eval_tracking_top_final.json` `results/4/detection/raw/f1` | 0.918 | ok |
| REPORT §7.2 | eval precision | 0.872 | `outputs/eval_tracking_top_final.json` `results/4/detection/raw/precision` | 0.872 | ok |
| REPORT §7.2 | eval recall | 0.97 | `outputs/eval_tracking_top_final.json` `results/4/detection/raw/recall` | 0.97 | ok |
| REPORT §7.2 | eval F1 referees removed | 0.984 | `outputs/eval_tracking_top_final.json` `results/4/detection/referee_removed/f1` | 0.984 | ok |
| REPORT §7.2 | eval team accuracy % | 98.4 | `outputs/eval_tracking_top_final.json` `results/4/teams/accuracy_settled` | 98.4 | ok |
| REPORT §7.2 | eval IDF1 | 0.526 | `outputs/eval_tracking_top_final.json` `results/4/identity/idf1` | 0.526 | ok |
| REPORT §7.2 | eval ID switches per player-min | 1.8 | `outputs/eval_tracking_top_final.json` `results/4/identity/id_switches_per_player_minute` | 1.8 | ok |
| README, REPORT §7.2 | eval2 F1 at 1 m raw | 0.93 | `outputs/eval_second_set_tracking_top_final.json` `results/4/detection/raw/f1` | 0.93 | ok |
| REPORT §7.2 | eval2 F1 referees removed | 0.99 | `outputs/eval_second_set_tracking_top_final.json` `results/4/detection/referee_removed/f1` | 0.99 | ok |
| REPORT §7.2 | eval2 team accuracy % | 98.8 | `outputs/eval_second_set_tracking_top_final.json` `results/4/teams/accuracy_settled` | 98.8 | ok |
| REPORT §7.2 | eval2 IDF1 | 0.457 | `outputs/eval_second_set_tracking_top_final.json` `results/4/identity/idf1` | 0.457 | ok |
| REPORT §7.2 | eval2 ID switches per player-min | 1.41 | `outputs/eval_second_set_tracking_top_final.json` `results/4/identity/id_switches_per_player_minute` | 1.41 | ok |
| REPORT §7.2 | eval White formation exact % | 100 | `outputs/eval_real_final.json` `top/eval/oracle/home/formation/exact_agreement` | 100.0 | ok |
| REPORT §7.2 | eval Blue formation exact % | 90 | `outputs/eval_real_final.json` `top/eval/oracle/away/formation/exact_agreement` | 90.0 | ok |
| REPORT §7.2 | eval2 White formation exact % | 93.5 | `outputs/eval_second_set_real_final.json` `top/eval2/oracle/home/formation/exact_agreement` | 93.5 | ok |
| REPORT §7.2 | eval2 Blue formation exact % | 88.1 | `outputs/eval_second_set_real_final.json` `top/eval2/oracle/away/formation/exact_agreement` | 88.1 | ok |
| REPORT §7.2 | calibration held-out mean error m (top) | 0.11 | `data/calibration/top.json` `errors/held_out_mean_m` | 0.11 | ok |
| REPORT §7.2 | autodetect correct of 180 | 180 | `outputs/eval_autodetect.json` `outcomes/success` | 180.0 | ok |
| README, REPORT §7.3, DEVPOST | Zenodo test F1 before | 0.567 | `outputs/eval_zenodo_before.json` `test/detection/1m/f1` | 0.567 | ok |
| REPORT §7.3 | Zenodo test precision before | 0.396 | `outputs/eval_zenodo_before.json` `test/detection/1m/precision` | 0.396 | ok |
| REPORT §7.3 | Zenodo test recall before | 0.999 | `outputs/eval_zenodo_before.json` `test/detection/1m/recall` | 0.999 | ok |
| README, REPORT §7.3, DEVPOST | Zenodo test F1 after | 0.855 | `outputs/eval_zenodo_final.json` `test/detection/1m/f1` | 0.855 | ok |
| REPORT §7.3 | Zenodo test precision after | 0.765 | `outputs/eval_zenodo_final.json` `test/detection/1m/precision` | 0.765 | ok |
| REPORT §7.3 | Zenodo test recall after | 0.97 | `outputs/eval_zenodo_final.json` `test/detection/1m/recall` | 0.97 | ok |
| REPORT §7.3 | detections per frame before | 63.1 | `outputs/eval_zenodo_before.json` `test/per_frame/detections` | 63.1 | ok |
| REPORT §7.3 | detections per frame after | 31.7 | `outputs/eval_zenodo_final.json` `test/per_frame/detections` | 31.7 | ok |
| REPORT §7.3 | annotated people per frame | 25 | `outputs/eval_zenodo_final.json` `test/per_frame/annotated_people` | 25.0 | ok |
| REPORT §7.3 | team accuracy before % | 81 | `outputs/eval_zenodo_before.json` `test/teams/accuracy` | 81.0 | ok |
| REPORT §7.3 | team accuracy after % | 98 | `outputs/eval_zenodo_final.json` `test/teams/accuracy` | 98.0 | ok |
| REPORT §7.3 | strict coverage home after % | 96 | `outputs/eval_zenodo_final.json` `test/formation_coverage_strict/home/coverage` | 96.0 | ok |
| REPORT §7.3 | strict coverage away after % | 76 | `outputs/eval_zenodo_final.json` `test/formation_coverage_strict/away/coverage` | 76.0 | ok |
| REPORT §7.3 | strict coverage home before % | 0 | `outputs/eval_zenodo_before.json` `test/formation_coverage_strict/home/coverage` | 0.0 | ok |
| REPORT §7.3 | strict coverage away before % | 10 | `outputs/eval_zenodo_before.json` `test/formation_coverage_strict/away/coverage` | 10.0 | ok |
| REPORT §7.3 | worst corner error m, final run | 1.4 | `outputs/eval_zenodo_final.json` `autodetect_vs_annotations/max_corner_error_m` | 1.4 | ok |
| REPORT §7.3 | worst corner error m, first run | 1.74 | `outputs/eval_zenodo_before.json` `autodetect_vs_annotations/max_corner_error_m` | 1.74 | ok |
| README, REPORT §7.4 | 4K F1 raw | 0.928 | `outputs/teamtrack_720p_check/report.json` `rows/4k/detection/raw/f1` | 0.928 | ok |
| REPORT §7.4 | 4K team accuracy % | 99 | `outputs/teamtrack_720p_check/report.json` `rows/4k/teams/accuracy_settled` | 99.0 | ok |
| REPORT §7.4 | 4K IDF1 | 0.468 | `outputs/teamtrack_720p_check/report.json` `rows/4k/identity/idf1` | 0.468 | ok |
| REPORT §7.4 | 4K White formation exact % | 91.7 | `outputs/teamtrack_720p_check/report.json` `rows/4k/formation/home/exact_agreement` | 91.7 | ok |
| REPORT §7.4 | 4K Blue formation exact % | 86.2 | `outputs/teamtrack_720p_check/report.json` `rows/4k/formation/away/exact_agreement` | 86.2 | ok |
| REPORT §7.4 | 4K s per video s | 1.42 | `outputs/teamtrack_720p_check/report.json` `rows/4k/seconds_per_video_second` | 1.42 | ok |
| README, REPORT §7.4 | 720p F1 raw | 0.928 | `outputs/teamtrack_720p_check/report.json` `rows/720p/detection/raw/f1` | 0.928 | ok |
| REPORT §7.4 | 720p team accuracy % | 98.5 | `outputs/teamtrack_720p_check/report.json` `rows/720p/teams/accuracy_settled` | 98.5 | ok |
| REPORT §7.4 | 720p IDF1 | 0.416 | `outputs/teamtrack_720p_check/report.json` `rows/720p/identity/idf1` | 0.416 | ok |
| REPORT §7.4 | 720p White formation exact % | 74.1 | `outputs/teamtrack_720p_check/report.json` `rows/720p/formation/home/exact_agreement` | 74.1 | ok |
| REPORT §7.4 | 720p Blue formation exact % | 82.8 | `outputs/teamtrack_720p_check/report.json` `rows/720p/formation/away/exact_agreement` | 82.8 | ok |
| REPORT §7.4 | 720p s per video s | 0.34 | `outputs/teamtrack_720p_check/report.json` `rows/720p/seconds_per_video_second` | 0.34 | ok |
| REPORT §7.4 | 4K referees-removed F1 | 0.978 | `outputs/teamtrack_720p_check/report.json` `rows/4k/detection/referee_removed/f1` | 0.978 | ok |
| REPORT §7.4 | 720p referees-removed F1 | 0.958 | `outputs/teamtrack_720p_check/report.json` `rows/720p/detection/referee_removed/f1` | 0.958 | ok |
| REPORT §7.6 | TeamTrack sample total s | 20.6 | `outputs/sample_timing.json` `samples/0/total_s` | 20.6 | ok |
| REPORT §7.6 | TeamTrack sample pitch check s | 1.3 | `outputs/sample_timing.json` `samples/0/pitch_check_s` | 1.3 | ok |
| REPORT §7.6 | TeamTrack sample analysis s | 19.3 | `outputs/sample_timing.json` `samples/0/analysis_s` | 19.3 | ok |
| REPORT §7.6 | Zenodo sample total s | 18.5 | `outputs/sample_timing.json` `samples/1/total_s` | 18.5 | ok |
| REPORT §7.6 | Zenodo sample pitch check s | 1.1 | `outputs/sample_timing.json` `samples/1/pitch_check_s` | 1.1 | ok |
| REPORT §7.6 | Zenodo sample analysis s | 17.3 | `outputs/sample_timing.json` `samples/1/analysis_s` | 17.3 | ok |
| REPORT §7.6 | TeamTrack sample px per metre | 14 | `outputs/sample_timing.json` `samples/0/resolution/px_per_m` | 14.0 | ok |
| REPORT §7.6 | Zenodo sample px per metre | 14.7 | `outputs/sample_timing.json` `samples/1/resolution/px_per_m` | 14.7 | ok |
| DEVPOST | Zenodo s per video s, loaded laptop | 13.13 | `outputs/eval_zenodo_before.json` `s_per_video_s` | 13.13 | ok |
| DEVPOST | Zenodo s per video s, idle laptop | 4.39 | `outputs/eval_zenodo_a4_before.json` `s_per_video_s` | 4.39 | ok |
| REPORT §4.5 | Zenodo base s per frame | 0.888 | `outputs/a4_geo_bench_c2f.json` `zenodo/base/s_per_frame` | 0.888 | ok |
| REPORT §4.5 | Zenodo base ORB frames of 24 | 21 | `outputs/a4_geo_bench_c2f.json` `zenodo/base/orb_frames` | 21.0 | ok |
| REPORT §4.5 | Zenodo c2f s per frame | 0.097 | `outputs/a4_geo_bench_c2f.json` `zenodo/c2f0.5/s_per_frame` | 0.097 | ok |
| REPORT §4.5 | Zenodo c2f ORB frames | 0 | `outputs/a4_geo_bench_c2f.json` `zenodo/c2f0.5/orb_frames` | 0.0 | ok |
| REPORT §4.5 | Zenodo base line error m | 0.075 | `outputs/a4_geo_bench_c2f.json` `zenodo/base/line_err_median_m` | 0.075 | ok |
| REPORT §4.5 | Zenodo c2f line error m | 0.079 | `outputs/a4_geo_bench_c2f.json` `zenodo/c2f0.5/line_err_median_m` | 0.079 | ok |
| REPORT §4.5 | TeamTrack dev base s per frame | 0.089 | `outputs/a4_geo_bench_c2f.json` `teamtrack_dev/base/s_per_frame` | 0.089 | ok |
| REPORT §4.5 | TeamTrack dev c2f s per frame | 0.089 | `outputs/a4_geo_bench_c2f.json` `teamtrack_dev/c2f0.5/s_per_frame` | 0.089 | ok |
| REPORT §4.5 | TeamTrack dev line error m | 0.087 | `outputs/a4_geo_bench_c2f.json` `teamtrack_dev/base/line_err_median_m` | 0.087 | ok |
| REPORT §4.5 | plain downscale 0.125 s per frame | 0.035 | `outputs/a4_geo_bench.json` `zenodo/scale0.125/s_per_frame` | 0.035 | ok |
| REPORT §4.5 | plain downscale 0.125 line error m | 0.121 | `outputs/a4_geo_bench.json` `zenodo/scale0.125/line_err_median_m` | 0.121 | ok |
| REPORT §4.5 | Zenodo a4_before F1 | 0.8553 | `outputs/eval_zenodo_a4_before.json` `test/detection/1m/f1` | 0.8553 | ok |
| REPORT §4.5 | Zenodo a4_before precision | 0.7648 | `outputs/eval_zenodo_a4_before.json` `test/detection/1m/precision` | 0.7648 | ok |
| REPORT §4.5 | Zenodo a4_before team accuracy % | 98.25 | `outputs/eval_zenodo_a4_before.json` `test/teams/accuracy` | 98.25 | ok |
| REPORT §4.5 | Zenodo a4_before geometry s | 109.9 | `outputs/eval_zenodo_a4_before.json` `timing_s/geometry` | 109.9 | ok |
| REPORT §4.5 | Zenodo a4_before s per video s | 4.39 | `outputs/eval_zenodo_a4_before.json` `s_per_video_s` | 4.39 | ok |
| REPORT §4.5 | Zenodo a4_after F1 | 0.8533 | `outputs/eval_zenodo_a4_after.json` `test/detection/1m/f1` | 0.8533 | ok |
| REPORT §4.5 | Zenodo a4_after precision | 0.7616 | `outputs/eval_zenodo_a4_after.json` `test/detection/1m/precision` | 0.7616 | ok |
| REPORT §4.5 | Zenodo a4_after team accuracy % | 98.1 | `outputs/eval_zenodo_a4_after.json` `test/teams/accuracy` | 98.1 | ok |
| REPORT §4.5 | Zenodo a4_after geometry s | 18.2 | `outputs/eval_zenodo_a4_after.json` `timing_s/geometry` | 18.2 | ok |
| REPORT §4.5 | Zenodo a4_after s per video s | 1.29 | `outputs/eval_zenodo_a4_after.json` `s_per_video_s` | 1.29 | ok |
| REPORT §4.5 | TeamTrack eval a4_before F1 | 0.9185 | `outputs/eval_tracking_top_a4_before.json` `results/4/detection/raw/f1` | 0.9185 | ok |
| REPORT §4.5 | TeamTrack eval a4_before s per video s | 1.269 | `outputs/eval_tracking_top_a4_before.json` `results/4/seconds_per_video_second` | 1.269 | ok |
| REPORT §4.5 | TeamTrack eval a4_before White formation % | 100 | `outputs/eval_real_a4_before.json` `top/eval/oracle/home/formation/exact_agreement` | 100.0 | ok |
| REPORT §4.5 | TeamTrack eval a4_before Blue formation % | 90 | `outputs/eval_real_a4_before.json` `top/eval/oracle/away/formation/exact_agreement` | 90.0 | ok |
| REPORT §4.5 | TeamTrack eval a4_after F1 | 0.9185 | `outputs/eval_tracking_top_a4_after.json` `results/4/detection/raw/f1` | 0.9185 | ok |
| REPORT §4.5 | TeamTrack eval a4_after s per video s | 1.227 | `outputs/eval_tracking_top_a4_after.json` `results/4/seconds_per_video_second` | 1.227 | ok |
| REPORT §4.5 | TeamTrack eval a4_after White formation % | 100 | `outputs/eval_real_a4_after.json` `top/eval/oracle/home/formation/exact_agreement` | 100.0 | ok |
| REPORT §4.5 | TeamTrack eval a4_after Blue formation % | 90 | `outputs/eval_real_a4_after.json` `top/eval/oracle/away/formation/exact_agreement` | 90.0 | ok |
| REPORT §4.2 | ablation without shadows: F1 | 0.709 | `outputs/eval_zenodo_fno_shadows.json` `test/detection/1m/f1` | 0.709 | ok |
| REPORT §4.2 | ablation without shadows: strict coverage home % | 0 | `outputs/eval_zenodo_fno_shadows.json` `test/formation_coverage_strict/home/coverage` | 0.0 | ok |
| REPORT §4.2 | ablation without shadows: strict coverage away % | 40 | `outputs/eval_zenodo_fno_shadows.json` `test/formation_coverage_strict/away/coverage` | 40.0 | ok |
| REPORT §4.2 | ablation without shadows: crop_exclude_lines recorded off | 0 | `outputs/eval_zenodo_fno_shadows.json` `selfcal/switches/crop_exclude_lines` | 0.0 | ok |
| REPORT §4.2 | ablation without crop_foreground: strict coverage home % | 33 | `outputs/eval_zenodo_fno_crop_foreground.json` `test/formation_coverage_strict/home/coverage` | 33.0 | ok |
| REPORT §4.2 | ablation without crop_foreground: strict coverage away % | 51 | `outputs/eval_zenodo_fno_crop_foreground.json` `test/formation_coverage_strict/away/coverage` | 51.0 | ok |
| REPORT §4.2 | ablation without crop_foreground: crop_exclude_lines recorded off | 0 | `outputs/eval_zenodo_fno_crop_foreground.json` `selfcal/switches/crop_exclude_lines` | 0.0 | ok |
| REPORT §4.2 | ablation without adaptive_gate: strict coverage home % | 8 | `outputs/eval_zenodo_fno_adaptive_gate.json` `test/formation_coverage_strict/home/coverage` | 8.0 | ok |
| REPORT §4.2 | ablation without adaptive_gate: strict coverage away % | 73 | `outputs/eval_zenodo_fno_adaptive_gate.json` `test/formation_coverage_strict/away/coverage` | 73.0 | ok |
| REPORT §4.2 | ablation without adaptive_gate: crop_exclude_lines recorded off | 0 | `outputs/eval_zenodo_fno_adaptive_gate.json` `selfcal/switches/crop_exclude_lines` | 0.0 | ok |
| REPORT §4.2 | ablation without local_scale: strict coverage home % | 92 | `outputs/eval_zenodo_fno_local_scale.json` `test/formation_coverage_strict/home/coverage` | 92.0 | ok |
| REPORT §4.2 | ablation without local_scale: strict coverage away % | 79 | `outputs/eval_zenodo_fno_local_scale.json` `test/formation_coverage_strict/away/coverage` | 79.0 | ok |
| REPORT §4.2 | ablation without local_scale: crop_exclude_lines recorded off | 0 | `outputs/eval_zenodo_fno_local_scale.json` `selfcal/switches/crop_exclude_lines` | 0.0 | ok |
| REPORT §4.2 | ablation without static_objects: strict coverage home % | 91 | `outputs/eval_zenodo_fno_static_objects.json` `test/formation_coverage_strict/home/coverage` | 91.0 | ok |
| REPORT §4.2 | ablation without static_objects: strict coverage away % | 79 | `outputs/eval_zenodo_fno_static_objects.json` `test/formation_coverage_strict/away/coverage` | 79.0 | ok |
| REPORT §4.2 | ablation without static_objects: crop_exclude_lines recorded off | 0 | `outputs/eval_zenodo_fno_static_objects.json` `selfcal/switches/crop_exclude_lines` | 0.0 | ok |
| REPORT §4.2 | ablation without grass_model: strict coverage home % | 96 | `outputs/eval_zenodo_fno_grass_model.json` `test/formation_coverage_strict/home/coverage` | 96.0 | ok |
| REPORT §4.2 | ablation without grass_model: strict coverage away % | 76 | `outputs/eval_zenodo_fno_grass_model.json` `test/formation_coverage_strict/away/coverage` | 76.0 | ok |
| REPORT §4.2 | ablation without grass_model: crop_exclude_lines recorded off | 0 | `outputs/eval_zenodo_fno_grass_model.json` `selfcal/switches/crop_exclude_lines` | 0.0 | ok |
| REPORT §4.2 | ablation without pitch_mask: strict coverage home % | 96 | `outputs/eval_zenodo_fno_pitch_mask.json` `test/formation_coverage_strict/home/coverage` | 96.0 | ok |
| REPORT §4.2 | ablation without pitch_mask: strict coverage away % | 76 | `outputs/eval_zenodo_fno_pitch_mask.json` `test/formation_coverage_strict/away/coverage` | 76.0 | ok |
| REPORT §4.2 | ablation without pitch_mask: crop_exclude_lines recorded off | 0 | `outputs/eval_zenodo_fno_pitch_mask.json` `selfcal/switches/crop_exclude_lines` | 0.0 | ok |
| REPORT §4.2 | first ablation without crop_foreground: strict home % | 58.2 | `outputs/eval_zenodo_no_crop_foreground.json` `test/formation_coverage_strict/home/coverage` | 58.2 | ok |
| REPORT §4.2 | first ablation without crop_foreground: strict away % | 38.8 | `outputs/eval_zenodo_no_crop_foreground.json` `test/formation_coverage_strict/away/coverage` | 38.8 | ok |
| REPORT §4.2 | first ablation without crop_foreground: crop_exclude_lines recorded on | 1 | `outputs/eval_zenodo_no_crop_foreground.json` `selfcal/switches/crop_exclude_lines` | 1.0 | ok |
| REPORT §4.2 | first ablation without adaptive_gate: strict home % | 4.5 | `outputs/eval_zenodo_no_adaptive_gate.json` `test/formation_coverage_strict/home/coverage` | 4.5 | ok |
| REPORT §4.2 | first ablation without adaptive_gate: strict away % | 61.2 | `outputs/eval_zenodo_no_adaptive_gate.json` `test/formation_coverage_strict/away/coverage` | 61.2 | ok |
| REPORT §4.2 | first ablation without adaptive_gate: crop_exclude_lines recorded on | 1 | `outputs/eval_zenodo_no_adaptive_gate.json` `selfcal/switches/crop_exclude_lines` | 1.0 | ok |
| REPORT §4.2 | final strict coverage home % | 96 | `outputs/eval_zenodo_final.json` `test/formation_coverage_strict/home/coverage` | 96.0 | ok |
| REPORT §4.2 | final strict coverage away % | 76 | `outputs/eval_zenodo_final.json` `test/formation_coverage_strict/away/coverage` | 76.0 | ok |
| REPORT §8 | 4-3-3 = 4-2-3-1 family: hits 34 -> 28 | 28 | `outputs/eval_synthetic_heldout2_cheq.json` `all/changes/hits` | 28.0 | ok |
| REPORT §8 | 4-3-3 = 4-2-3-1 family: false positives 34 -> 16 | 16 | `outputs/eval_synthetic_heldout2_cheq.json` `all/changes/false_positives` | 16.0 | ok |
| REPORT §7.5, README | 23 Oct upload (c2f absent): candidates | 8 | `outputs/upload_check/demo_final_full/upload_check.json` `summary/candidates` | 8.0 | ok |
| REPORT §7.5 | 23 Oct upload (c2f absent): s per video s | 3.06 | `outputs/upload_check/demo_final_full/upload_check.json` `perception/s_per_video_s` | 3.06 | ok |
| REPORT §7.5 | 23 Oct upload (c2f absent): geometry s | 559.6 | `outputs/upload_check/demo_final_full/upload_check.json` `perception/timing_s/geometry` | 559.6 | ok |
| REPORT §7.5 | 23 Oct upload (c2f absent): wall s | 2738.6 | `outputs/upload_check/demo_final_full/upload_check.json` `wall_s` | 2738.6 | ok |
| REPORT §7.5 | 23 Oct upload (c2f absent): OpenCV re-analysis s | 1388.7 | `outputs/upload_check/demo_final_full/upload_check.json` `summary/opencv_reanalysis_s` | 1388.7 | ok |
| REPORT §7.5, README | 24 Oct upload (c2f ON): candidates | 8 | `outputs/upload_check/demo_c2f_full/upload_check.json` `summary/candidates` | 8.0 | ok |
| REPORT §7.5 | 24 Oct upload (c2f ON): s per video s | 2.75 | `outputs/upload_check/demo_c2f_full/upload_check.json` `perception/s_per_video_s` | 2.75 | ok |
| REPORT §7.5 | 24 Oct upload (c2f ON): geometry s | 424.1 | `outputs/upload_check/demo_c2f_full/upload_check.json` `perception/timing_s/geometry` | 424.1 | ok |
| REPORT §7.5 | 24 Oct upload (c2f ON): wall s | 2703.1 | `outputs/upload_check/demo_c2f_full/upload_check.json` `wall_s` | 2703.1 | ok |
| REPORT §7.5 | 24 Oct upload (c2f ON): OpenCV re-analysis s | 1434.5 | `outputs/upload_check/demo_c2f_full/upload_check.json` `summary/opencv_reanalysis_s` | 1434.5 | ok |
| REPORT §7.5 | 24 Oct upload: confirmed decisions | 2 | `outputs/upload_check/demo_c2f_full/upload_check.json` `summary/decisions/confirmed` | 2.0 | ok |
| REPORT §7.5 | 24 Oct upload: rejected decisions | 1 | `outputs/upload_check/demo_c2f_full/upload_check.json` `summary/decisions/rejected` | 1.0 | ok |
| REPORT §7.5 | 24 Oct upload: uncertain decisions | 5 | `outputs/upload_check/demo_c2f_full/upload_check.json` `summary/decisions/uncertain` | 5.0 | ok |
| REPORT §7.5 | 23 Oct upload: uncertain decisions | 6 | `outputs/upload_check/demo_final_full/upload_check.json` `summary/decisions/uncertain` | 6.0 | ok |
| REPORT §4.5 | eval2 c2f F1 raw | 0.93 | `outputs/eval_second_set_tracking_top_c2f.json` `results/4/detection/raw/f1` | 0.93 | ok |
| REPORT §4.5 | eval2 c2f F1 referees removed | 0.99 | `outputs/eval_second_set_tracking_top_c2f.json` `results/4/detection/referee_removed/f1` | 0.99 | ok |
| REPORT §4.5 | eval2 c2f team accuracy % | 98.8 | `outputs/eval_second_set_tracking_top_c2f.json` `results/4/teams/accuracy_settled` | 98.8 | ok |
| REPORT §4.5 | eval2 c2f IDF1 | 0.457 | `outputs/eval_second_set_tracking_top_c2f.json` `results/4/identity/idf1` | 0.457 | ok |
| REPORT §4.5 | eval2 c2f ID switches per player-min | 1.41 | `outputs/eval_second_set_tracking_top_c2f.json` `results/4/identity/id_switches_per_player_minute` | 1.41 | ok |
| REPORT §4.5 | eval2 c2f White formation exact % | 93.6 | `outputs/eval_second_set_real_c2f.json` `top/eval2/oracle/home/formation/exact_agreement` | 93.6 | ok |
| REPORT §4.5 | eval2 c2f Blue formation exact % | 88.1 | `outputs/eval_second_set_real_c2f.json` `top/eval2/oracle/away/formation/exact_agreement` | 88.1 | ok |
| REPORT §4.5 | eval2 c2f White coverage % | 99.3 | `outputs/eval_second_set_real_c2f.json` `top/eval2/oracle/home/coverage/pipeline` | 99.3 | ok |
| README, REPORT §7.6 | TeamTrack sample new size MB | 32.3 | `outputs/sample_clip_reencode.json` `rows/crf16/bytes` | 32.3 | ok |
| REPORT §7.6 | TeamTrack sample old size MB | 218.4 | `outputs/sample_clip_reencode.json` `rows/old/bytes` | 218.4 | ok |
| REPORT §7.6 | CRF 23 copy size MB (rejected) | 8.6 | `outputs/sample_clip_reencode.json` `rows/crf23/bytes` | 8.6 | ok |
| REPORT §7.6 | CRF 12 copy size MB (rejected, too big) | 63.2 | `outputs/sample_clip_reencode.json` `rows/crf12/bytes` | 63.2 | ok |
| REPORT §7.6 | new sample px per metre | 14 | `outputs/sample_clip_reencode.json` `rows/crf16/px_per_m` | 14.0 | ok |
| REPORT §7.6 | new sample candidates | 0 | `outputs/sample_clip_reencode.json` `rows/crf16/candidates` | 0.0 | ok |
| REPORT §7.6 | new sample median position difference to the old file m | 0.03 | `outputs/sample_clip_reencode.json` `rows/crf16/vs_reference/median_position_diff_m` | 0.03 | ok |
| REPORT §7.6 | referee-labelled detections, old file | 180 | `outputs/sample_clip_reencode.json` `rows/old/label_counts/referee` | 180.0 | ok |
| REPORT §7.6 | referee-labelled detections, new sample | 124 | `outputs/sample_clip_reencode.json` `rows/crf16/label_counts/referee` | 124.0 | ok |
| REPORT §7.6 | referee-labelled detections, CRF 23 copy | 75 | `outputs/sample_clip_reencode.json` `rows/crf23/label_counts/referee` | 75.0 | ok |
| REPORT §6, §7.6, DEPLOY | EC2 TeamTrack sample total s | 23.5 | `outputs/sample_timing_ec2.json` `samples/0/total_s` | 23.5 | ok |
| REPORT §6 | EC2 TeamTrack sample pitch check s | 3.4 | `outputs/sample_timing_ec2.json` `samples/0/pitch_check_s` | 3.4 | ok |
| REPORT §6 | EC2 TeamTrack sample analysis s | 20.2 | `outputs/sample_timing_ec2.json` `samples/0/analysis_s` | 20.2 | ok |
| REPORT §6 | EC2 TeamTrack sample s per video s | 0.55 | `outputs/sample_timing_ec2.json` `samples/0/perception/s_per_video_s` | 0.55 | ok |
| REPORT §6, §7.6, DEPLOY | EC2 Zenodo sample total s | 23 | `outputs/sample_timing_ec2.json` `samples/1/total_s` | 23.0 | ok |
| REPORT §6 | EC2 Zenodo sample pitch check s | 2.9 | `outputs/sample_timing_ec2.json` `samples/1/pitch_check_s` | 2.9 | ok |
| REPORT §6 | EC2 Zenodo sample analysis s | 20.1 | `outputs/sample_timing_ec2.json` `samples/1/analysis_s` | 20.1 | ok |
| REPORT §6 | EC2 Zenodo sample s per video s | 0.56 | `outputs/sample_timing_ec2.json` `samples/1/perception/s_per_video_s` | 0.56 | ok |
| REPORT §6, §10 | EC2 6-min upload server wall s | 1679.9 | `outputs/ec2_upload_6min_24oct.json` `progress_detail/elapsed_s` | 1679.9 | ok |
| REPORT §6 | EC2 6-min upload detection stage s | 403.2 | `outputs/ec2_upload_6min_24oct.json` `progress_detail/stage_timings_s/detecting` | 403.2 | ok |
| REPORT §6 | EC2 6-min upload agent stage s | 1272.2 | `outputs/ec2_upload_6min_24oct.json` `progress_detail/stage_timings_s/agent` | 1272.2 | ok |
| REPORT §4.5, §6 | EC2 6-min upload s per video s | 1.13 | `outputs/ec2_upload_6min_24oct.json` `perception/s_per_video_s` | 1.13 | ok |
| REPORT §4.5 | EC2 6-min upload geometry s | 148.1 | `outputs/ec2_upload_6min_24oct.json` `perception/timing_s/geometry` | 148.1 | ok |
| REPORT §6 | EC2 6-min upload OpenCV re-analysis s | 1064.9 | `outputs/ec2_upload_6min_24oct.json` `summary/opencv_reanalysis_s` | 1064.9 | ok |
| REPORT §6 | EC2 6-min upload candidates | 8 | `outputs/ec2_upload_6min_24oct.json` `summary/candidates` | 8.0 | ok |
| REPORT §6 | EC2 6-min upload confirmed | 2 | `outputs/ec2_upload_6min_24oct.json` `summary/decisions/confirmed` | 2.0 | ok |
| REPORT §6 | EC2 6-min upload rejected | 3 | `outputs/ec2_upload_6min_24oct.json` `summary/decisions/rejected` | 3.0 | ok |
| REPORT §6 | EC2 6-min upload uncertain | 3 | `outputs/ec2_upload_6min_24oct.json` `summary/decisions/uncertain` | 3.0 | ok |
| REPORT §6 | EC2 6-min upload Bedrock calls | 49 | `outputs/ec2_upload_6min_24oct.json` `summary/bedrock/calls` | 49.0 | ok |
| REPORT §6 | EC2 6-min upload Bedrock USD | 0.052 | `outputs/ec2_upload_6min_24oct.json` `summary/bedrock/cost_usd` | 0.052 | ok |
| REPORT §6 | EC2 6-min upload posture calls | 2 | `outputs/ec2_upload_6min_24oct.json` `summary/posture/calls` | 2.0 | ok |
| REPORT §6 | EC2 6-min upload posture USD | 0.0031 | `outputs/ec2_upload_6min_24oct.json` `summary/posture/cost_usd` | 0.0031 | ok |


### 5.2 Read by hand from prose records (no JSON to compare)

| claim | where used | source | ok |
|---|---|---|---|
| EC2: sample clip 12.7 s wall; 6-min 4K upload 1,888 s (detection 464 s, agent 1,412 s, OpenCV re-analysis 1,208 s); health 200 in 0.57 s; chat answer 5.4 s; 593.6 MB in 14 assets; 31.5 min | REPORT §6, §7.6, limitations | `RECORD.md` N6a items (3), (3b), (4), `deploy/DEPLOY_AWS.md` "Observed" | ok (read) |
| $0.13 per hour, $3.10 per day running, $0.22 per day stopped; `m7i-flex.large` | REPORT §6 | `deploy/DEPLOY_AWS.md` "Costs" | ok (read; prices from the AWS price list on 22 Oct) |
| Trace (a): 52 % coverage, 11.3 s check, 6 fps, 91 % of 11 readings; (b): 55 s revert, 17 % of 12; (c): 190 px/s, 30 % zoom, lines 33 % | REPORT §5B, DEVPOST | `docs/AGENT_TRACE_EXAMPLES.md` | ok (read) |
| Calibration tiers: detections 21.8 → 12.8, White points 8.3 → 2.6, labelled share 0.86 → 0.77; 5.9 % duplicates at 9.3 px/m; the 69 % came from a generated 7.4 px/m clip | REPORT §8 | `RECORD.md` 23 Oct (two entries), `docs/FAILURE_LOG.md` 2026-10-23 | ok (read) |
| Upload consistency: 73 % of 11 windows; 8 of 9 candidates matched; 6 uncertain; 1,200 s budget | REPORT §7.5 | `RECORD.md` 23 Oct generalisation entry, `FAILURE_LOG.md` 2026-10-23 | ok (read) |
| Task A: false alerts 23 → 19, changes 67 → 66; return-leg: 67 → 67 and 23 → 48; line drop 1.70 per match | REPORT §8 | `CLAUDE.md` Key numbers, `AGENT_DESIGN.md` §8/§14, `FAILURE_LOG.md` 2026-10-17 | read in docs; raw experiment JSON **not re-checked** |
| Drone classical detector F1 0.906; tiled YOLOX recall 0.06 / 0.54 at 18 s per frame; side F1 0.49 raw, 0.78 at 2 m, 3.4 s per frame | REPORT §7.2, §8 | `CLAUDE.md` Key numbers (from `outputs/compare_detectors_*.json`) | read in docs; **not re-checked against the JSON** |
| ID switches "about 10 % higher" (1.61 → 1.80, 1.31 → 1.41); 0.99 → 1.17 s per video second | REPORT limitation 10 | `RECORD.md` 23 Oct; before-values from `CLAUDE.md` Key numbers | after-values checked in 5.1; **before-values not re-checked** |
| 55 failure-log entries | DEVPOST | `grep -c "^### \[" docs/FAILURE_LOG.md` = 55 | ok (counted) |
| Caps: 300 calls and $1.00 per day; $0.30 per analysis; agent 150 calls, 400 k tokens, $0.50 per match; chat 20 questions per visitor per day | REPORT §5, Responsible use | `config.yaml` (`api.bedrock_daily`, `api.jobs`, `agent.limits`, `api.chat`) | ok (read) |
| Verify thresholds: lines fitted ≥ 90 %, shift ≤ 25 px/s, zoom ≤ 3 %, persistence 60 % | REPORT §5 | `outputs/eval_agent_final.json` `verify` block | ok (read) |
| Zenodo sample 1080p: 900 frames, 1920×1080, 20.6 MB | docs | `scripts/make_sample_clip.py` run on 24 Oct (`RECORD.md`) | ok |

## 6. Devpost requirements (taken from the author's paste of the official page; the page itself was not re-read)

| requirement | where | status |
|---|---|---|
| Report sections: problem, users (grassroots coaches), architecture, OpenCV 5 implementation, AWS deployment, evaluation, limitations, responsible use | `docs/TECHNICAL_REPORT.md` §1, §2, §3, §4, §6, §7, "Honest limitations", "Responsible use" | **met** |
| Responsible use covers: no faces or identities, youth footage policy, licensed data with credit, what goes to Bedrock (numbers and short text, never pixels), cost caps and budgets, the coach approves every alert, "uncertain" instead of guessing | "Responsible use" (six bullets) | **met** |
| "Agentic Vision Award evidence" section: workflow diagram, trace examples where an OpenCV result changes a later call or decision, evaluation of task success, failure handling, observability, human control | `TECHNICAL_REPORT.md` "Agentic Vision Award evidence" A–D; diagram `docs/agent_workflow.png`; traces `docs/AGENT_TRACE_EXAMPLES.md` | **met**; linked from the top of the README |
| Demo script opens with the team (name, FAST-NUCES, Pakistan) | `docs/DEMO_SCRIPT.md` §1 | **met** (name to confirm, section 0 item 2) |
| Demo shows the architecture diagram and the main results on screen | `DEMO_SCRIPT.md` §10 and shot 10 | **met** |
| Devpost text says plainly that AI coding assistants (Claude Code, Codex) helped write the code and that the author designed, directed, tested and reviewed it | `docs/DEVPOST.md` "How we built it" | **met** |
| Repo public or shared with judges | section 0 item 1 | **NOT MET: author action** |
| Video at most 5 min, no copyrighted music | `DEMO_SCRIPT.md` targets 4:45, no music | planned; the video is not recorded |

## 7. Every placeholder

| placeholder | meaning | where |
|---|---|---|
| `TBD-REPO` | link of the public repository once the author makes it public | `docs/DEVPOST.md:3`, `docs/DEVPOST.md:82` |
| `TBD-VIDEO` | link of the demo video once it is recorded and uploaded | `README.md:9`, `docs/DEVPOST.md:3`, `docs/DEVPOST.md:81`, `docs/DEMO_SCRIPT.md:102` |

## 8. Things I was unsure about

- **Author name** (section 0).
- **The "421 s" geometry claim in the task description.** It comes from `outputs/eval_zenodo_final.json`, which was measured while the laptop was busy. The same baseline on an idle laptop takes 110 s of geometry (134 s wall); the report says so. The 3.4× speed-up is idle laptop to idle laptop.
- **A4 (`drift.coarse_to_fine`) re-checked on 24 Oct (morning)** on what the overnight run had not covered: the demo window as one 4K upload (same 8 candidates, White 16:30 and Blue both still confirmed, 73 % of 11 and 75 % of 12 windows; 3.06 → 2.75 s per video second, one candidate moved from uncertain to rejected, cause not investigated) and TeamTrack `eval2` (F1, teams, IDF1 identical; White formation 93.5 → 93.6 %; pipeline candidates 6 → 4, both oracle changes still matched). Decision: stays ON. Neither upload was a controlled benchmark. Deployed the same afternoon: on EC2 the 6-minute upload's detection stage took 403.2 s (1.13 s per video second, geometry 148.1 s); not an A/B of the switch alone, since the 22 Oct build also lacked the self-calibration.
- **Ablation numbers.** The task asked for a note that the ablation was taken with `crop_exclude_lines` on. That is true for the first set (`eval_zenodo_no_*.json`), but a second set under the final config exists (`eval_zenodo_fno_*.json`); the report quotes both and says which is which.
- **Zenodo corner error** differs between runs of the same code (worst corner 1.74, 1.4 and 1.22 m in three runs); the report quotes the first two.
- **Screenshot 07** shows the chat on a server with Bedrock off (an "unavailable" message), because no real Bedrock call was allowed. The live site answers from stored results.
- **Zenodo sample team names**: the app labels the two teams "White" and "Blue" (the TeamTrack defaults) even on the Zenodo clip, whose kits are red-and-white and white.
- **`web/scripts/upload-ux.mjs`** (committed earlier) still mocks the legacy `GET /api/sample`, which the server keeps for compatibility; the page now reads `/api/samples`. Its file-upload checks are unaffected; its sample path is not exercised.
- **Low-resolution threshold** 12.0 px/m: midway between 9.3 (720p copy) and about 14.7 (1080p); the two 1080p samples measure 14.0 and 14.7. A 1080p video in which the pitch does not fill the frame width would be flagged: intended, but "1080p" alone does not guarantee no note.
- **EC2 timings** were measured on 24 Oct after the redeploy (sections 4 and 5.1: `outputs/sample_timing_ec2.json`, `outputs/ec2_upload_6min_24oct.json`). The 22 Oct comparison values (12.7 s sample, 1,892.9 s upload) are read from the CloudWatch `analysis_done` lines and `RECORD.md`, not from a JSON file. The 6-minute test ran with Bedrock on (Nova arm), so its decisions (2 confirmed, 3 rejected, 3 uncertain) differ from the rules-arm laptop run (2 / 1 / 5) only in what the agent's re-analysis could read inside the frozen budget; not investigated further.
- **Logo:** option 3 ("Tactics board, checked") is applied: header (landing and `/app`), footer, favicon (SVG + 16/32 PNG), 180 px apple-touch icon, README top, screenshots 01–08 retaken. The other two options exist only in `docs/logo_options.png`. The social preview image (`web/public/og-image.png`, 1200 x 630, `web/scripts/render-og.mjs`) and its Open Graph / Twitter tags with the absolute URL were added on 24 Oct after the deploy; they are not on the server until the next redeploy. The landing page's product screenshot `web/public/product/app-desk.jpg` (17 Oct) still shows the old logo in its header; it was not retaken. The "favicon in a tab" screenshots (`web/screenshots/logo/favicon-tab-*.png`) are a composite: headless Chromium has no tab strip, so they show the page's real title next to the real favicon file at 16 / 32 / 64 px.
- The LinkedIn link is unverified (HTTP 999 to scripts).
- **TeamTrack sample re-encode:** the 218.4 MB file was replaced by a 32.3 MB H.264 CRF 16 copy only after the analysis matched (same pitch, formations, 0 candidates; median position difference 0.03 m). Referee-labelled detections are 124 against 180, a difference that does not change any formation (`outputs/sample_clip_reencode.json`). The old file is kept locally as `data/sample_clips/teamtrack_top_sample_1080p.old-218MB.mp4` (gitignored); delete it when you like. The S3 object is not replaced yet (command in `deploy/DEPLOY_AWS.md`).
- **Sample timings** (20.6 s and 18.5 s) are from the idle overnight run with the old TeamTrack file; a morning re-timing ran on a busy laptop (70.3 s and 64.1 s, the unchanged Zenodo sample included) and is kept in `outputs/sample_timing_busy_24oct_morning.json` but not quoted.
