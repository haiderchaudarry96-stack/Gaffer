# Failure log

> **Why this file exists.** The OpenCV competition explicitly asks for "evaluation evidence â€¦ including failure cases or limitations", and the technical report must cover limitations and responsible use. Most teams invent these in the last hour and it shows. Log each failure **when it happens**, with a screenshot, while the details are fresh. The best entries become slides in the video.

---

## Entry template

```
### [YYYY-MM-DD] Short title
**Stage:** detection / tracking / team colour / homography / camera motion / formation / change detection / agent / AWS
**Severity:** wrong output | degraded | crash

**Input:** clip + timestamp, or synthetic scenario
**What happened:**
**Why (best guess):**
**Screenshot / output:** outputs/failures/<file>.png
**Fix or mitigation:** fixed in <commit> | mitigated by <how> | known limitation
**Measured impact:** e.g. accuracy 78% â†’ 84% after fix
```

---

## Entries

<!-- Add entries here, newest first. -->

### [2026-10-23] Low-resolution video: players detected twice, so the shape before a change reads 4-2-3-1 (generated upload test)
**Stage:** detection (self-calibration `local_scale`), exposed by the adaptive team gate
**Severity:** wrong output (pre-change shape on generated footage; the agent's decision is right)

**Input:** `tests/test_api.py::test_upload_end_to_end_agent_confirms_a_real_change`: generated 960Ã—600 match (flat-colour discs, 7.4 px per metre), White 4-4-2 â†’ 3-5-2 at 1:15, 4 coach-clicked corners, the final 23 Oct config.
**What happened:** the confirmed change reads **White 4-2-3-1 â†’ 3-5-2** at 1:20 (held 80 % of 10 windows, no revert) instead of 4-4-2 â†’ 3-5-2; White's windows read 4-2-3-1 for the whole first 85 s; a second candidate (3-5-2 â†’ 4-2-3-1 at 2:15) is left uncertain (clip ends). The old test checked the exact "4-4-2 -> 3-5-2" and failed.
**Why (measured, gate on vs off on this clip only):** not a colour error. With `local_scale` the 960 px clip is processed at full resolution and **69 % of White player-frames have 2+ detections**, every extra one within 1.5 m of a real player (5 % with `local_scale` off; the extra detections are White's own pixels and move with the players, so the static filter does not touch them). The adaptive gate labels real White players White more often (47.8 % vs 34.0 % of matches) and labels the duplicates White too, so White has 15â€“18 "outfield" points per frame for 10 players and the 4-4-2 fits the neighbouring template 4-2-3-1. With the fixed gate many duplicates and real players stay unlabelled (12â€“14 points) and the shape happens to read 4-4-2. An experiment that kept the detector's morphology metric at low resolution made duplicates worse (87 %): not the fix, not kept.
**Screenshot / output:** outputs/pytest_final.log (before the test change)
**Fix or mitigation:** test changed (user decision rule: only the pre-change label differs and the change is still confirmed): it now requires exactly one confirmed change, White, new shape 3-5-2, within Â±30 s of 75 s, plus all earlier evidence/event checks; the pre-change shape is not checked and the test comment says why. **Duplicate detections on low-resolution video stay open** (no detector or gate change; Zenodo and TeamTrack are 4K, ~29 px/m, working scale 0.5, and do not show it).
**Measured impact:** White players with 2+ detections: 69 % (local scale on) vs 5 % (off) on this clip; test passes with the stricter checks.

### [2026-10-23] Upload vs demo mismatch, cause isolated: White's 16:30 change hinged on one 5 s window during a free kick
**Stage:** team colour / formation (perception in a set piece; the tactics engine is unchanged)
**Severity:** wrong output (a real change missing from the upload's candidate list)

**Input:** the demo's 6 minutes (TeamTrack drone 900â€“1260 s) as one file: the EC2 upload of 22 Oct (`D_20220220_1_0900_1260.mp4`, treated as a known clip: saved 31-point calibration re-anchored to its first frame) and, on 23 Oct, `data/sample_clips/teamtrack_top_0900_1260_4k.mp4` through the normal upload path on the laptop (auto-detected corners, confidence 0.991, confirmed; `scripts/upload_check.py`), compared with the demo record `samples/w900_1260` (the same tactics engine run on every MatchState, player positions matched frame by frame, labels and per-team coverage compared, and the oracle `outputs/oracle_top_full.json` as ground truth).
**What happened:** both uploads list every demo candidate except **White 4-4-2 â†’ 3-4-3 at 16:30**, the demo's one confirmed change; the upload's report says White had "no settled shape 15:00â€“16:30".
**Why (measured, step 0):** not the team model (the demo also fitted its own on the same 6 minutes; centres within 0.15 CIELAB units, gates 5.67 / 11.46 vs 5.77 / 11.30 â€” the 22 Oct guess "full-match team model" was wrong), not the attacking direction (same once the 4-corner frame's 180Â° rotation is undone), and only marginally the calibration (positions 0.25â€“0.29 m apart median; labels 97â€“98 % identical). What matters: in 15:45â€“16:30 White defends a **free kick**, its players stand in a wall and on the goal line, and only 7.1â€“7.6 of its 10 outfield players are visible with a White label (13â€“16 % called referee: crops with goal-line paint, merged wall blobs; White's red keeper loses the one goalkeeper slot per goal to a longer "other" track). White's 4-4-2 window confidences sit at 0.49â€“0.83 against the 0.45 threshold; in the demo the 15:55 window read 4-4-2 at 0.49, in the uploads 4-2-3-1 at 0.52â€“0.54, so the 4-4-2 held 15 s instead of `min_persist_s` = 20 s and 3-4-3 at 16:30 opened a segment instead of being a change. With perfect (ground-truth) positions the same engine on the same 6 minutes finds the change (4-4-2 held 15:35â€“15:55, 0.46â€“0.75). The Blue 3-5-2 â†’ 4-4-2 confirmed on EC2 was a demo candidate too, simply never checked in the demo run.
**Screenshot / output:** `outputs/upload_check/demo_before_perc/upload_check.json` (before), `outputs/upload_check/demo_final_perc/upload_check.json`, `outputs/upload_check/demo_final_full/upload_check.json` (after).
**Fix or mitigation:** general, no TeamTrack special case: the per-video self-calibration (entry above), in particular the team colour from each detection's own foreground pixels (each part of a split wall blob from its own pixels) and the adaptive gate. Result: White â†’ 3-4-3 at 16:30 is now a candidate in the upload, but read as **4-2-3-1 â†’ 3-4-3** (the shape during the free kick, which the ground-truth positions also show for parts of 15:56â€“16:40); Blue's 16:30 change likewise reads 4-2-3-1 â†’ 4-4-2 at 16:25. Through the full upload path (rules arm, no Bedrock, laptop): **White â†’ 3-4-3 at 16:30 is confirmed** (new shape held in 73 % of 11 confident windows, no revert; evidence image + pending alert), and Blue's 16:25 change is confirmed (75 % of 12), as on EC2. The other six candidates came out uncertain because the frozen 1,200 s re-analysis budget was spent on the first two (1,389 s measured on a laptop running other 4K jobs at the same time); their first pass suggests reject for five, the sixth lacks look-ahead footage at the clip end. Not fixed: the 'from' shape still reads 4-2-3-1, and the result still rests on set-piece windows.
**Measured impact:** demo candidates with an upload candidate of the same team and new shape (Â±90 s): 8 of 9 before (White 16:30 missing) â†’ 8 of 9 after (White 16:30 found; Blue 4-2-3-1 â†’ 3-5-2 at 16:05 no longer a candidate); with the same "from" shape too: 8 of 9 â†’ 6 of 9. The demo's confirmed change confirmed by the upload path: 0 of 1 (EC2, 22 Oct) â†’ 1 of 1 (laptop, 23 Oct).

### [2026-10-23] Unseen ground (Zenodo drone clip): shadows, poles and touchline clutter became "players", and the team colours collapsed
**Stage:** detection / team colour (drone perception on footage it was never built on)
**Severity:** wrong output

**Input:** Zenodo 10.5281/zenodo.14867795 (Synowiec, Nowak, Kamola, CC BY 4.0) `top-view-preview.mp4`: a different ground, artificial turf, low sun, red-and-white vs white kits; 30 s, 4K, the pitch at 29.4 px/m. Pitch auto-detect: accepted, 0.987, line error 0.08 m. Scored against the dataset's own annotations (`scripts/eval_zenodo.py`; annotation frame = video frame + 1900, measured). Settings chosen only on the TeamTrack dev clip and the first 10 s; **unseen test = 10â€“26.7 s**.
**What happened:** 63 detections per frame for 25 people (precision 0.40, recall 1.00, F1 0.57 at 1 m): each light-pole shadow cut into a dozen blobs, the fence band and spare balls by the far touchline, painted-line junctions, and every player's own long shadow as a second detection; 10.5 detections per frame on or just outside the lines. The junk captured one of the two team-colour clusters (its "team" centre was dark green, L* â‰ˆ 15), so only 41 % of players got a team (45 % "referee") and no team ever had 8 correctly labelled outfield players in a frame.
**Why:** the classical detector and the team crops were tuned on one overcast TeamTrack day: a fixed grass hue band, no notion of shadow, crops averaged over every non-grass pixel of a 1.2 m box. Shadowed turf keeps the grass hue only in pole shadows; in the core of a player's shadow it shifts towards cyan (hue median 66 vs 47 for sunlit turf), stays highly saturated and is half as bright, so it passed as "not grass".
**Screenshot / output:** outputs/failures/2026-10-23_unseen_ground_before.png, outputs/failures/2026-10-23_unseen_ground_after.png (frame at 20 s with team-coloured boxes above the 2D pitch; grey rings = annotated people).
**Fix or mitigation:** per-video self-calibration, OpenCV only, every part a switch in `perception.self_calibration` (`perception/selfcal.py`): a grass model learnt from the first frame's pitch pixels (`cv2.calcHist` hue peak, robust percentiles); shadows = darker, cyan-shifted, saturated turf â†’ background, thin elongated blobs rejected; expected player size from the homography at each blob and a working resolution set to 14.7 px/m; static objects = detections recurring at the same pitch point in â‰¥ 60 % of frames (pitch coordinates, so drone drift does not matter); pitch mask (1.5 m); team colour from the player's own foreground pixels (each part of a split blob from its own pixels); team gate = 1.5 Ã— the 90th-percentile colour distance, bounded by 0.15â€“0.7 Ã— the distance between the two kits. A switch that leaves painted-line pixels out of the crops was built and measured but left **off** (Zenodo tuning third: team accuracy 0.96 â†’ 0.85 with it; TeamTrack dev neutral).
**Measured impact (unseen test part, 10â€“26.7 s):** precision **0.40 â†’ 0.77**, recall 1.00 â†’ 0.97, **F1 0.57 â†’ 0.86** (1 m; same at 2 m); detections per frame 63 â†’ 32 (25 annotated); on/just outside the lines 10.5 â†’ 6.0 per frame (none beyond 1.5 m in either run); players given a team **41 % â†’ 95 %**, team accuracy 81 â†’ 98 %; frames with â‰¥ 8 correctly labelled annotated outfield players **0 / 10 % â†’ 96 / 76 %** (the two teams). TeamTrack regression (eval / eval2): detection F1 0.912 â†’ 0.918 / 0.922 â†’ 0.930, team accuracy 98.6 â†’ 98.4 % / 99.0 â†’ 98.8 % (unknown 2.4 â†’ 1.0 % / 1.9 â†’ 1.2 %), IDF1 0.515 â†’ 0.526 / 0.448 â†’ 0.457, formation agreement White 100 â†’ 100 % / 89.1 â†’ 93.5 %, Blue 89.7 â†’ 90.0 % / 88.1 â†’ 88.1 %; White coverage 91.2 â†’ 95.8 % / 97.8 â†’ 99.3 %; candidates 4 â†’ 5 (eval, all 3 oracle changes matched in both) / 6 â†’ 6. Costs: ID switches 1.61 â†’ 1.80 per player-minute on eval (tracks more fragmented), perception 0.99 â†’ 1.17 s per video second (TeamTrack dev clip, 4K, idle laptop; detection 80 â†’ 117 ms per frame). **Still weak:** pitch-side staff within 1 m of the touchline and some line junctions remain (6 detections per frame outside the lines), the pitch auto-detect is 1.7 m off at one corner against the annotation-implied corners, and this is one 30 s clip of one ground.

### [2026-10-22] Same 6 minutes of footage, different result through the upload path (EC2)
**Stage:** formation / change detection (upload path vs the Phase 3 demo pipeline)
**Severity:** wrong output (for the demo story: the confirmed change is a different team)

**Input:** the 12 TeamTrack drone clips 900â€“1260 s joined into one 360.4 s 4K MP4 (packets copied, no re-encode), uploaded to the live EC2 server (N6a, `up_fcb6687fdc86`, Nova arm, frozen rules `ca4ff9bbf7b01c6c`).
**What happened:** 8 candidates; the only confirmed one is **Blue 3-5-2 â†’ 4-4-2 at 16:30** (held 67 % of 12 windows). White's **4-4-2 â†’ 3-4-3 at 16:30**, the change the Phase 3 demo run confirmed in the same minutes (`samples/w900_1260`, 91 % held), is not a candidate at all: White's first candidate is 3-4-3 â†’ 4-3-3 (rejected), i.e. White was already read as 3-4-3.
**Why (best guess, not isolated):** the upload path differs from the Phase 3 run in two inputs: it fits its own team-colour model on these 6 minutes (Phase 3 used the full-match team model `<match>.teams.json`) and it re-anchors the saved 31-point calibration to the upload's first frame (the reference clip is not on the server). Either can change who is White and which shape is read before 16:30. Nothing points at EC2 (same image as the laptop, x86_64 OpenCV 5.0.0).
**Screenshot / output:** live result `http://13.210.196.109/api/analyses/fcb6687fdc86/result`; evidence `â€¦/evidence/evt_002.jpg`.
**Fix or mitigation:** known limitation for now; the demo keeps the Phase 3 record. To isolate: run the same upload on the laptop, then with the full-match team model, then with the reference clip present. **Update 23 Oct:** cause isolated (not the team model, not EC2): see the 2026-10-23 entry "Upload vs demo mismatch, cause isolated".
**Measured impact:** demo-window agreement between the two paths on confirmed changes: 0 of 1.

### [2026-10-22] Posture read on the first real upload event failed validation (fallback "unclear")
**Stage:** agent (N3 posture, `agent/posture.py`)
**Severity:** degraded (safe fallback; the verifier's confirmed decision was unaffected)

**Input:** EC2 upload `up_fcb6687fdc86`, evt_002 (Blue 3-5-2 â†’ 4-4-2), Nova 2 Lite, 1 call (1,529 in / 421 out tokens, $0.0015).
**What happened:** Nova answered `unclear` with **no citations**; the result failed schema validation (`malformed_result:ValidationError`), so the event is stored `posture_status: failed` with the deterministic fallback `unclear`. Only the output hash is kept (`posture_trace`, CloudWatch stream `posture_trace`), not the text.
**Why (best guess):** an `unclear` answer without the required citation list does not fit the typed result; the 22 Oct fix covered `unclear` answers that still cited metrics.
**Fix or mitigation:** not fixed in N6a (deployment only). Candidate fix: accept a model `unclear` with an empty citation list as a completed `unclear` (it makes no claim to cite).
**Measured impact:** 1 of 1 real upload posture calls on EC2 failed validation.

### [2026-10-22] Free plan refuses Graviton: t4g.large launch rejected
**Stage:** AWS
**Severity:** degraded (deployment on a different instance type)

**Input:** `aws ec2 run-instances --instance-type t4g.large` in ap-southeast-2 on the Free-plan account.
**What happened:** `InvalidParameterCombination: The specified instance type is not eligible for Free Tier.` Eligible in Sydney: t3.micro/small, t4g.micro/small, t8i.micro/small, c7i-flex.large, m7i-flex.large.
**Fix or mitigation:** launched **m7i-flex.large** (2 vCPU Intel, 8 GiB, $0.1197/h). No larger type is available on this plan, so the 6-min 4K upload takes 31.5 min on the server (detection 464 s; agent re-analysis uses the full 1,200 s OpenCV budget).
**Measured impact:** detection 1.29 s per video second on EC2 vs 1.18 on the laptop.

### [2026-10-22] Chat invented an event id for "Why was Blue's 18:50 change rejected?" (twice)
**Stage:** agent (analyst chat, `api/chat.py`)
**Severity:** degraded (the grounding check caught it; the coach got the safe "can't answer" reply)

**Input:** demo match w900_1260, real Nova 2 Lite, 3 calls per run, 2 runs (21 Oct, fix session).
**What happened:** Nova called `get_decision` with `evt_018` (the real id is `evt_007`), then answered citing `evt_012` / `evt_018`. Every answer was flagged ("evt_018 is not a candidate of this match") and replaced by `SAFE_ANSWER`. After the first fix (the unknown-id error now lists the real candidates, and the prompt says never to guess an id), the second run still guessed `evt_018` first and then answered from it instead of calling again.
**Why (best guess):** the model maps "18:50" to an id-like token instead of calling `list_candidate_changes` first.
**Fix or mitigation:** the question now carries a one-line index of the match's candidates (id, team, clock, change), and the unknown-id error lists them (`test_chat_unknown_event_id_lists_the_real_candidates`). **Not re-tested on Bedrock** (session budget used). The grounding check worked as designed: nothing wrong reached the coach.
**Measured impact:** before: 2 of 2 live runs ungrounded ($0.0041, 6 calls). After: not measured.

### [2026-10-21] Every real Bedrock posture call was stored as "failed" (guard, format and citation contract)
**Stage:** agent (N3 posture, `agent/posture.py`)
**Severity:** degraded (fallback "unclear"; the verifier's decision was never affected)

**Input:** demo evt_003 (White 4-4-2 -> 3-4-3, 16:30) and a generated upload; 3 real calls (N5 x 2, audit x 1).
**What happened:** all three were rejected as `model_made_unsupported_ball_possession_pressure_or_intent_claim`. The audit saved the raw answer: it tripped on an honest limitation ("No pressing_index data available â€¦"), was wrapped in a ```json fence (unparseable), and cited `defensive_line_m` / `m` instead of the validator's `opencv_metrics.after.defensive_line_m` / `m (attacking-direction-normalized)`, which the prompt never stated.
**Why (best guess):** the keyword check scanned the whole raw text (limitations included) while the prompt asked for limitations; the citation contract was implicit.
**Fix or mitigation:** fence stripped before parsing; the keyword check reads the explanation (the claim) only; the evidence lists every citable entry (`citable_metrics`) and the prompt states the format; a model "unclear" on weak evidence is kept as a Bedrock result. The confidence floor (0.45) and the paired-metric rule are unchanged. Tests in `tests/test_posture.py`.
**Measured impact:** one real call after the fix (22 Oct, $0.0012): **completed / unclear**, 4 exact citations (line 11.5 -> 20.1 m, width 22.7 -> 47.7 m); Nova proposed a directional label and the code downgraded it because the window before 16:30 is too uncertain (`weak_quality_low_segment_confidence`, confidence 0.30). Stored in the demo seed `samples/w900_1260/demo_events_seed.json`.

### [2026-10-17] Pitch auto-detect put one goal line on the edge of the artificial turf (all 180 drone test frames wrong, accepted at 0.91)
**Stage:** homography (OpenCV pitch auto-detect for uploads, `perception/pitch.py: detect_pitch_corners`)
**Severity:** wrong output, accepted with high confidence
**Input:** `py scripts\eval_autodetect.py` on the laptop: all 60 TeamTrack drone clips (0â€“1800 s), 3 frames each, reference = the 31-point calibration; "correct" = every corner within 1 m. First real-footage run of the auto-detect (it had only been built and tested on generated frames).
**What happened:** **0 / 180 correct, all 180 accepted** (confidence 0.81â€“0.91). Left, top and bottom edges were right; the right edge sat on the edge of the artificial turf 6â€“7 m behind the goal line (max corner error median 6.75 m, worst 14.67 m when the grass ran to the frame border; player positions off by 2.67 m median).
**Why:** each edge was snapped to the *outermost* straight painted-looking line with â‰¥ 80 % of the best support. Behind one goal line the turf edge is just as straight and bright, so it won. The confidence missed it because the markings check only scored the median distance of the markings it *did* find (0.09 m, same as the true corners); the 19 % of marking samples with no painted line within 2 m only lowered the score linearly.
**Screenshot / output:** outputs/failures/2026-10-17_autodetect_turf_edge_before_after.jpg (top: before, bottom: after); the 180 "before" overlays are in the gitignored `outputs/_peek/autodetect_before/`.
**Fix or mitigation:** fixed 17 Oct. Each edge now keeps up to 3 painted-line candidates (plus the grass edge); every combination is projected through its 4-corner homography and the one whose IFAB markings (halfway line, boxes, circle) land on painted lines wins (fewest markings without paint nearby, then smallest median). Search widened from 12 % to 20 % of the pitch depth. Confidence: the markings part is now 0 when â‰¥ 20 % of marking samples find no paint (`calibration.auto_detect.confidence.max_markings_not_found`). New test `test_autodetect_ignores_a_straight_line_outside_the_goal_line` (generated pitch with a decoy line 6.5 m behind the goal line: old code 62 px off, new code < 4 px).
**Measured impact:** 180 frames, same clips: **correct 0 / 180 â†’ 180 / 180** (all accepted, confidence 0.94â€“0.99); max corner error median **6.75 m â†’ 0.19 m** (p90 0.21, worst 0.27 m); player positions vs the 31-point calibration median **2.67 m â†’ 0.07 m** (worst 0.24 m); tilted and cropped frames still refused. Detection time ~0.34 s â†’ ~0.9 s per frame (VM; once per upload). **Caveat:** the fix was designed after seeing these failures and measured on the same 60 clips of one pitch, so this is not a held-out number; a different ground (other surroundings, worn lines, a camera that is not straight above) may still fail, which is why the coach always confirms the outline.


### [2026-10-17] Generated clip with worn markings: White's shirts mostly not given a team, so no White shape and no candidates
**Stage:** team colour (upload through the web app, Phase 4 integration check)
**Severity:** wrong output (on generated footage)
**Input:** generated top-down clip, 960 Ã— 600, 120 s, 8 fps (`tests/videogen.py` frames with the painted lines faded to 20 %, White switching 4-4-2 â†’ 3-5-2 at 0:50); OpenCV pitch auto-detect was unsure (correctly: faint lines), the coach marked the 4 corners in the browser.
**What happened:** the analysis finished, but of 6,218 player detections only 1,463 were labelled home (White), 2,666 away, 1,021 referee and 1,068 unknown: White never reached 8 labelled outfield players often enough for a shape, the engine produced 0 candidates and the desk showed "No shape changes found" with most White players as hollow (unassigned) rings. For comparison, the 3-min generated clip with full-strength markings uploaded in the same check (switch at 1:15): home 4,221 / away 4,169 of 9,617 detections, 3 candidates, the change confirmed.
**Why (best guess):** the team model is fitted per upload; with the faded paint blended into the grass, one team's colour gate came out at 5.0 (7.4 on the clean clip), so many torsos fell outside it and went to "other" (referee / unknown). Generated footage, so it says little about real worn pitches, but it is the honest outcome of that upload.
**Screenshot / output:** web/screenshots/integrate/14-needs-corners-result-desk.png
**Fix or mitigation:** none (perception not tuned in the integration session). The UI states plainly that no changes were found and shows unassigned players as rings, never guessed.
**Measured impact:** share of all detections labelled home 44 % (clean clip) vs 24 % (worn markings); candidates 3 vs 0.

### [2026-10-17] Web app rejected every real upload result: agent traces now contain "explanation" steps
**Stage:** web app (data validation), found by the Phase 4 end-to-end check
**Severity:** crash (of the result view: "The analysis did not start or finish")
**Input:** the first generated upload analysed by the API and loaded by the connected frontend.
**What happened:** `GET /api/analyses/{id}/result` returned 200, but `validateTraceStep` threw on `kind: "explanation"`, so the desk never showed the result. The demo trace (`samples/`) predates build step 7 and has no such step, so the frontend's own tests could not catch it.
**Why (best guess):** the frontend was written against the step-6 trace; step 7 added the checked-explanation step to the trace after the decision.
**Screenshot / output:** none (caught in the walkthrough log); fixed result: web/screenshots/integrate/08-upload-result-desk.png
**Fix or mitigation:** fixed (branch `phase4-integrate`): `explanation` is an accepted, untyped trace kind; a test covers it.
**Measured impact:** upload results shown: 0 / 1 â†’ 2 / 2 in the walkthrough.

### [2026-10-17] Coach report: Nova's version does not pass the grounding check; the code template is published
**Stage:** agent (coach report, `agent/report.py`, build step 7)
**Severity:** degraded (the LLM's part of the report; the published report is the template)
**Input:** the 900â€“1260 s demonstration window (1 confirmed, 1 rejected, 7 unchecked candidates, 9 timeline segments); before that, prompt work on dev seed 45 (synthetic, 6 confirmed, 4 rejected).
**What happened:** the check (every number or time cited, numbers present in the cited items, valid sources only, each "may have fixed" and each of 3 recommendations built on a cited number) rejected Nova's report on the real window twice: attempt 1 had 3 problems (an uncited sentence with numbers, a "may have fixed" with no number, a `[match.note]` pseudo-citation), attempt 2 only the `[match.note]` citation, although the prompt says the note needs none. Its content was grounded but tactically weak ("Deepen the defensive line to match White's drop to 16.8 m", "Add a third central defender to mirror White's shift to a 3-4-3"). On dev seed 45: first prompt, wrong JSON types, then uncited clocks and numbers not in the cited items; second prompt, accepted but generic ("Possibly this was meant to fix their depth"); stricter check, rejected twice (a 55.2 m line cited to the wrong event, a 38:00 clock not in the cited event).
**Why (best guess):** a small model asked for many cited numbers in free prose attributes them loosely; the check is strict by design (a wrong number in a coach report is worse than a plain one).
**Screenshot / output:** outputs/agent_video_step7/report_w900_1260.md (published, template), report_w900_1260.json (both Nova attempts with their problems)
**Fix or mitigation:** the template (code, built from the same inputs) is published, as designed; it passes the same check (tested). Not tuned further on the real window. A `[match.note]`-style slip could be stripped as a format error like a missing explanation citation (open, not done).
**Measured impact:** real window: 2 Nova calls, $0.0035, 0 accepted; dev seed 45: 5 runs (3 prompt versions, 10 calls, $0.038), 1 accepted.

### [2026-10-17] Real footage: one confirmed alert in a window chosen by the oracle; short clips leave a third of the candidates footage-limited
**Stage:** agent (video backend), real drone footage
**Severity:** limitation (what the real-footage evidence can and cannot show)

**Input:** frozen rules + Nova 2 Lite on (a) the drone eval / eval2 pipeline candidates (1260â€“1800 s, 11) and the side eval2 candidate (`outputs/agent_video_final/`), (b) a 6 min demonstration window 900â€“1260 s (`outputs/agent_video_taskE/`) **selected because the oracle shows the half's two sustained changes inside it**, so it is a demonstration, not a random sample, and it is the same match as every other clip.
**What happened:** (1) **Clip lengths:** eval2 and eval are 4.5 min each and the look-ahead needs 60 s after detection, so **4 of the 11** top candidates (eval2 evt_005/006, eval evt_004/005) sit within 60 s of the end and are uncertain by rule F whatever OpenCV sees (since 16 Oct without a re-analysis). The side eval2 set is 3 min; its only candidate is uncertain because a 140 s side re-analysis is refused on budget (estimated 1,568 s > 360 s) and the first pass is inconclusive (57 %). (2) On the 11 top candidates **nothing is confirmed** (7 rejected, 4 uncertain), and the decision never differs from the first pass alone. (3) In the demonstration window the pipeline finds both oracle changes; **w900 evt_003 (home 4-4-2 -> 3-4-3, 16:30) is confirmed** by both arms (first-pass coverage 52 % before -> re-analysis at 6 fps, 252 s; new shape in 91 % of 11 windows) with an evidence JPEG and a pending alert: the **only confirmed alert on real footage**. Its "before" panel uses the most confident 4-4-2 window, 15:15â€“15:45 (30 frames), where the team is packed inside its own box (very likely defending a set piece), so the picture overstates the change. w900 evt_007 (away 4-4-2 -> 4-2-3-1, 18:50, held 100 % on the second look) is rejected by rule R (return leg; entry below). The first pass alone would have given both decisions too.
**Why (best guess):** TeamTrack clips are 30 s, and our real sets are 4.5 min runs; a 60 s look-ahead costs ~1 min per set end. The real match changes shape often but rarely keeps a new one (oracle: 43 candidates, 2 sustained moves away from the usual 4-4-2).
**Screenshot / output:** outputs/agent_video_taskE/evidence/teamtrack_top_w900_1260/evt_003.jpg, outputs/agent_video_taskE/report.json, report_llm.json, trace_llm.jsonl; outputs/agent_video_final/report.json, report_llm.json
**Fix or mitigation:** reported as is. Longer windows reduce F losses (the full 0â€“1800 s is now local). **"Before" panel fixed 17 Oct (build step 7, rendering only):** measured on the demo window, every confident 4-4-2 window in the 45 s before 16:30 had White deep in its own half: 45â€“65 % of the outfield positions inside its own penalty area (15:15â€“15:55; open play later in the half: 0â€“9 %). The panels now take the most confident window of the shape with at most 25 % of positions in the own box (`presentation.evidence.max_own_box_share`), searching 120 s back for "before"; when every window is packed, the most confident one is drawn with an "ATYPICAL: x % in own box (deep defending or set piece?)" note. Re-rendered: before = 4-4-2 at 15:05â€“15:35 (confidence 0.78, 20 % in own box), after unchanged (3-4-3 16:35â€“17:05, 12 %). Threshold set on this one case (presentation only, no decision reads it). `outputs/agent_video_step7/evidence/teamtrack_top_w900_1260/evt_003.jpg`; old vs new panels: `outputs/failures/2026-10-17_evidence_before_panel_set_piece.jpg`.
**Measured impact:** 14 real candidates (11 top eval/eval2, 1 side, 2 demo): **1 confirmed** (demo window), 8 rejected, 5 uncertain (4 footage, 1 side budget); 0 decisions changed by the second look (1 reason changed: eval evt_001, "reverted after 55 s" -> "held in only 17 %").

### [2026-10-17] Real footage: Nova agrees with every rules decision, but half its explanations are wrong
**Stage:** agent (LLM arm, video backend)
**Severity:** wrong output (text only; decisions all equal to the rules)

**Input:** Nova 2 Lite on the 12 real candidates (`outputs/agent_video_final/report_llm.json`) and the 2 demonstration candidates (`outputs/agent_video_taskE/`).
**What happened:** **14 / 14 decisions equal the rules arm**, 0 fallbacks, 2 guard blocks (side). But **7 of 14 explanations are wrong**: 3 contradict the re-analysis they cite (eval2 evt_003 "no transition occurred" and eval evt_002 "not held for 10+ seconds", both held 75 %; w900 evt_007 "not held", held 100 %: all three are rejected as return legs, which the model does not mention), and all 4 footage-limited candidates are explained as "engine confidence insufficient" instead of missing footage. Nova picked 6 fps for every second look (the rules policy picks 4 fps unless coverage is low), which cost 5 extra uncached re-analyses (~950 s OpenCV).
**Why (best guess):** the model paraphrases the label strip rather than the `rules.failed` field; the verdict reason is in the result but not quoted.
**Screenshot / output:** outputs/agent_video_final/trace_llm.jsonl, outputs/agent_video_taskE/trace_llm.jsonl
**Fix or mitigation:** **fixed 17 Oct (build step 7, presentation only):** a separate explanation step after `record_decision` (`agent/explain.py`). Nova gets the code-written reason, the cause, the rule in plain words and the key numbers of the candidate's tool results by ref (no engine evidence string, no label strip) and writes 1-2 sentences. A cheap check (cause named, no contradiction, every number and clock present in the results, no ball/possession/pressing/confidence, refs exist) replaces a flagged text with a code template. The orchestration conversation, its prompt and budget are unchanged. Prompt developed on dev seed 45 only (4 runs, $0.012), then **one** run on the 14 real candidates (`scripts/explain_real.py`): the step-6 traces replayed (stored camera checks, cached re-analyses, no OpenCV), every rules verdict and decision asserted equal for both arms.
**Measured impact:** **wrong explanations 7 / 14 -> 0 / 14** (same rubric: contradicts the decision or names another cause). Stricter rubric (also a number or claim not in the cited result, e.g. "held 20 s", "40 % coverage" for a 40 % share, "reverted by 24:05" where the second look found no revert): 12 / 14 -> 0 / 14; one new text is vague but not false (eval evt_005 "looked like 4-4-2 for a moment": 2 readings in the last 10 s). Nova's new texts kept 12 / 14; replaced 2: side evt_001 (named no cause; right to replace), eval2 evt_005 (said "recorded", missing from the footage word list: a false flag, word added afterwards, not re-run). The check flags 12 / 14 of the old texts. First attempt: 8 of 14 calls could not reach Bedrock (connect timeout): all fell back to the template as designed, and only those 8 were re-tried. 14 calls, **$0.0046**. After the side candidate's recorded reason changed to lead with the experimental camera (step 7, task 3), its explanation was re-run once from the new reason: Nova named the camera and the text was kept. Final: Nova texts 13 / 14, template 1; 15 calls, $0.0049. `outputs/agent_video_step7/explanations.json`, `explain_real_run*.log`.

### [2026-10-17] Final run: Nova's decisions equal the rules', its alert text is formulaic
**Stage:** agent (LLM arm), final eval seeds 110â€“119
**Severity:** degraded (text only; every decision equals the rules arm)

**Input:** `eval_agent.py --set final --final --arms oneshot,rules,llm` (run once, 17 Oct), Nova 2 Lite, 68 candidates, 41 alerts.
**What happened:** 68 / 68 decisions equal the rules arm (0 guard blocks, 0 invalid calls, 0 fallbacks), so the LLM adds nothing to decisions. In the 41 alerts the model's explanation repeats the engine's persistence rule ("held for 20 seconds") in **31**, although the verified reason above it says 60 s of look-ahead; the suggestions are near-templates ("Consider adjusting midfield pressing â€¦" 14, "â€¦ pressure" 8, "â€¦ pressing intensity" 5). 23 of 68 candidates were decided with `record_decision` only (synthetic backend, design situation E: a first-pass revert rejects without a vision call).
**Why (best guess):** the candidate card's engine evidence string contains "held 20s"; the small model copies the most salient number. Tactical suggestions get no tactical context beyond the two formation names.
**Screenshot / output:** outputs/eval_agent_final/alerts_llm.jsonl, outputs/eval_agent_final/llm_rows.jsonl, outputs/eval_agent_final.json
**Fix or mitigation:** mitigated by design: the code-written verified reason is shown first in every alert (spike fix, 15 Oct). **Explanations fixed 17 Oct (build step 7, entry above):** the explanation step never sees the engine's evidence string, and its check rejects a "20 s" that no result contains (test `test_check_flags_the_17_oct_failure_texts`). The final run on 110-119 was not re-run (decisions frozen, scope); on dev seed 45 none of 10 new explanations says "held 20 s". Suggestions were still the model's free text, unchecked (open until 22 Oct: now checked against the formation change by `explain.check_suggestion` and replaced by `explain.suggestion_template` when wrong; the 16:30 demo alert now reads "White now has 3 at the back and 3 up front (was 4 and 2): check how your team matches up against the 3-4-3.").
**Measured impact:** 31 / 41 explanations restate the wrong persistence window; 0 / 68 decisions differ from the rules.

### [2026-10-17] "Strong persistence beats the return-leg rule" adds 25 false alerts on synthetic data (left OFF)
**Stage:** agent (rules verifier, rule R), experiment
**Severity:** limitation (fix tested, not adopted)

**Input:** proposed after the real oracle showed R rejecting away evt_033 (4-4-2 -> 4-2-3-1 at 18:50, held 220 s; entry below). Change: a return leg is rejected only when persistence fails (P >= 0.6 on >= 3 confident look-ahead windows, no reverse change -> judged like any candidate). No threshold. Evaluated on dev 42â€“52 + seeds 100â€“109 only (same evidence cache as Task A), leave-one-seed-out CV, kept only if <= +1 false alert per 10 matches and no lost hit (fixed in advance). `scripts/return_leg_experiment.py`.
**What happened:** in-sample: alerted real changes **67 -> 67**, false alerts **23 -> 48** (dev 4 -> 14, seeds 100â€“109 19 -> 34); CV picks "off" in **21 of 21** folds. All 25 changed decisions are false candidates moving from rejected to confirmed; 15 of them are 4-3-3 <-> 4-2-3-1 return legs (8 in seeds 104 / 105). Real oracle 0â€“1800 s (information only): 7 of 43 decisions would change rejected -> confirmed, evt_033 among them, but 6 of the 7 are returns to the team's usual 4-4-2.
**Why (best guess):** in the synthetic matches every real change is a single step to a new shape, so a return leg that persists for 60 s is the second half of a flip-flop, not a decision; on the real match, the persistent return legs are mostly the team going back to its base shape after a 30â€“60 s excursion. Neither is what a coach wants alerted, and evt_033 alone does not justify it.
**Screenshot / output:** outputs/return_leg_experiment.json, outputs/return_leg_experiment.log
**Fix or mitigation:** **left OFF** (`agent.verify.return_leg_needs_failed_persistence: false`, code kept as a measured option). Rule R unchanged; evt_033 stays a known miss on the real match.
**Measured impact:** +25 false alerts / +0 hits on 21 development matches if switched on.

### [2026-10-17] Shape metrics do not separate a real 4-3-3 <-> 4-2-3-1 change from a flip (Task A, rule left OFF)
**Stage:** agent (rules verifier), experiment
**Severity:** limitation (idea tested, not adopted)

**Input:** dev seeds 42â€“52 plus seeds 100â€“109 (**development data for this experiment only**; 110â€“119 never loaded), rules arm with the frozen thresholds, `scripts/flip_experiment.py`. Rule fixed before looking at data: a candidate the rules would confirm whose shapes are {4-3-3, 4-2-3-1} becomes uncertain when D = max(|d defensive line|, |d width|, |d compactness|) between [onset âˆ’ 45 s, onset] and [detection, detection + 60 s] on the re-analysed pass is <= T (one threshold, grid off / 0.5â€“8 m). T by leave-one-seed-out CV (21 folds, objective alerted hits âˆ’ false alerts); "clearly helps" fixed in advance as CV false alerts âˆ’5 or better with <= 2 real changes lost.
**What happened:** of the rules arm's 23 false alerts on the 21 matches, 14 are confirmed 4-3-3 <-> 4-2-3-1 flips, against 4 real changes of that pair. D does **not** separate them: flips 0.98â€“38.4 m (median ~10 m), real changes 1.09 / 11.9 / 14.5 / 25.6 m. Cross-validated: false alerts **23 -> 19**, alerted real changes **67 -> 66** (the real change with D = 1.09 m is lost); T = 7.5 m in 20 of 21 folds (7.0 m in one), the grid edge region, i.e. "turn most pair confirmations off". On seeds 100â€“109 alone: false alerts 19 -> 15, alerted 28 -> 27; dev unchanged (4 / 39).
**Why (best guess):** a flip in the synthetic matches is the team *really* moving (wide forwards dropping when out of possession), so its metrics move as much as a tactical switch; "no metric change" is not what distinguishes it. The distinguishing variable is possession, which the drone pipeline cannot see.
**Screenshot / output:** outputs/flip_experiment.json, outputs/flip_experiment.log
**Fix or mitigation:** **left OFF** (âˆ’4 false alerts < the âˆ’5 fixed in advance; not tuned further). Rules frozen 17 Oct after this. Better fix stays: classify in- and out-of-possession shapes separately (needs ball detection).
**Measured impact:** CV âˆ’4 false alerts / âˆ’1 real change if it had been switched on.

### [2026-10-17] Full first half (oracle): one candidate every 42 s, and the return-leg rule rejects a shape that then holds 220 s
**Stage:** change detection + agent (rules verifier), oracle (GT positions)
**Severity:** wrong output (known limitation; found on the real match, not tuned on)

**Input:** oracle MatchState of the drone view over 0â€“1800 s (60 clips, `teamtrack_to_matchstate.py --view top --set full`), tactics engine unchanged, rules arm on the annotation backend (`scripts/oracle_sustained.py --rules`).
**What happened:** (1) With perfect positions the engine emits **43 candidates in 30 min** (home 21, away 22). Home spends 56 % of the half in 4-4-2 and keeps flipping to 3-4-3 / 4-2-3-1 for 30â€“60 s; away moves between 4-4-2 (35 %), 4-2-3-1 (22 %) and 3-5-2/5-3-2 (25 %). Only 8 candidates hold >= 2 min with the new shape in >= 60 % of confident windows, and 6 of those are returns to the team's usual 4-4-2; 2 move away from it (home 4-4-2 -> 3-4-3 at 16:30, 130 s; away 4-4-2 -> 4-2-3-1 at 18:50, 220 s). Nothing holds longer than 4.5 min. (2) The rules confirm 6, reject 32, leave 5 uncertain. They **reject away evt_033 (4-4-2 -> 4-2-3-1 at 18:50), the longest new shape of the half (220 s, 78 % of 45 windows)**, as the return leg of evt_031, which was itself the return leg of evt_030 (4-4-2 -> 4-2-3-1 at 17:30, 4-2-3-1 -> 4-4-2 at 18:00): rule R looks one step back and cannot tell A->B->A->B from a flip-flop. (3) They confirm away evt_001 (5-3-2 -> 4-2-3-1 at 1:15), which then holds only 70 s.
**Why (best guess):** a 30 s window classifier on a grassroots-style match where players drift between lines; with no ball (no in/out-of-possession split) the shape label follows the phase of play. Rule R was designed on synthetic out-and-back pairs; a third leg after a quick double flip looks like a return.
**Screenshot / output:** outputs/oracle_top_full_changes.json, outputs/oracle_top_full_changes.log
**Fix or mitigation:** not changed (rules frozen for the final run; real footage is not a tuning set). Possible fix for later: rule R only when the earlier leg was not itself rejected as a return.
**Measured impact:** 1 of the 2 sustained "away from the usual shape" changes in the half is rejected by R.

### [2026-10-15] Real drone candidates: the second OpenCV look never changed a decision
**Stage:** agent (video backend, build step 5)
**Severity:** limitation (evidence for the Agentic Vision claim on real footage)

**Input:** all 11 pipeline candidates of the drone eval (1530-1800 s, 5) and eval2 (1260-1530 s, 6) MatchStates, rules arm (no LLM), video backend: `check_frame_quality` + `reanalyse_window` at 4 fps on [onset - 45 s, detection + 60 s] (`scripts/run_agent_video.py`).
**What happened:** 7 rejected, 4 uncertain (the clip ends before 60 s of look-ahead), 0 confirmed. In **11 of 11** the decision equals what the first pass alone gives. The camera was always fine (lines fit in 100 % of sampled frames, shift <= 2.4 px/s, zoom <= 0.1 %, no cut), so the quality check never changed the path either. The 4 fps re-analysis moved the share of windows in the new shape by at most 0.17 (eval2 evt_003 0.62 -> 0.75, evt_006 0.33 -> 0.50 on 3 -> 2 windows). Once it changed the evidence but not the decision: eval evt_001, first pass "reverted after 55 s", second look no revert but held in only 17 % of 12 windows -> still rejected. Two candidates **held** on the second look (eval2 evt_003 75 %, eval evt_002 73 %) but are return legs of an earlier rejected change, so R rejects them, consistently. The oracle (GT boxes) confirms none of its 5 candidates either.
**Why (best guess):** the drone pipeline is already close to the oracle (Phase 2: 89-100 % formation agreement), and the first pass already comes from 4 fps tracking; sampling the engine at 4 fps instead of 1 fps adds frames of the same quality. These candidates are out-and-back flips that perfect perception sees the same way.
**Screenshot / output:** outputs/agent_video/report.json, outputs/agent_video/trace_rules.jsonl, outputs/agent_video_run.log
**Fix or mitigation:** reported as is, not forced. The only real-frame case where OpenCV changes the next call and the decision is the **simulated pan/zoom** (real drone frames, sliding/zooming crop): `check_frame_quality` measures 190 px/s, 30 % zoom, lines fit in 33 % of frames -> refuse -> no re-analysis -> uncertain, where the first pass alone says reject. With no confirmed real candidate, the video evidence renderer is shown as a bannered render check on a real frame (`outputs/agent_video/render_check/`), not as an alert.
**Measured impact:** 0 of 11 real decisions changed by OpenCV; 1 of 11 changed evidence; simulated pan: 1 of 1 refused.

### [2026-10-15] Footage-limited candidates still pay for a 2-minute re-analysis that cannot change them
**Stage:** agent (rules on the video backend)
**Severity:** wasted compute (no wrong output)

**Input:** same run as above.
**What happened:** 4 of 11 real candidates (eval2 evt_005 / evt_006, eval evt_004 / evt_005) are within 60 s of the clip end. Rule F makes them uncertain whatever the evidence, but on video every verdict except a refusal waits for a second look, so each still ran a 104-127 s re-analysis: **477 s of the 1,545 s** of re-analysis in the run.
**Why:** design rule "on real video every decision except a refusal needs a second OpenCV look" (AGENT_DESIGN Â§3 E) does not except F, which no second look can fix.
**Screenshot / output:** outputs/agent_video/report.json (`reanalysis.processing_s` of those rows)
**Fix or mitigation:** **fixed 16 Oct (user-approved design change):** when F fails, the verdict is uncertain right after the camera check, with no second look (`verify.evaluate`; test `test_footage_limited_candidate_skips_the_second_look`). Re-run on the same 11 candidates (`scripts/run_agent_video.py --out outputs/agent_video_fskip`, cached re-analyses): **11 of 11 decisions unchanged**, 4 re-analyses not run.
**Measured impact:** the 4 skipped re-analyses had taken **455 s of the 1,444 s** of uncached re-analysis OpenCV time in the step-5 run (31 %; the 477 s / 1,545 s first written here counted wall time with pipeline overhead).

### [2026-10-15] Vision checks: the quality check is slower than designed, and drone re-anchoring absorbs a crop/zoom "pan"
**Stage:** agent (video backend `check_frame_quality`)
**Severity:** degraded (both measured, neither changes a decision)

**Input:** 11 real windows of ~140 s, plus a simulated pan/zoom of eval2 1300-1440 s (sliding crop at 150 px/s, crop share 0.75 +- 0.12, resized back to 4K, 2 fps).
**What happened:** (1) `check_frame_quality` takes **8-13 s** per call on the 4K drone video (design guess: 1-3 s): 12 frames decoded with H.264 seeks, plus 6 ECC re-anchorings. (2) On the simulated pan, the drone re-anchoring (affine ECC, ORB fallback) still fits the painted lines in **33 %** of frames: a pure crop + zoom of a nadir image is an affine change, which re-anchoring is built to undo. The camera-motion check (190 px/s, zoom 30 %) is what refuses it. A first version of the simulation jumped when the zoom changed the crop's travel range (measured 1,326 px/s); the crop range was then fixed for a smooth pan. (3) The first pair interval tried, 0.2 s, was too coarse: at 960 px analysis width, 1 px of noise is 20 px/s (a static drone read 17.6 px/s against the 25 px/s limit); pairs are 0.5 s apart now (static drone <= 2.4 px/s).
**Screenshot / output:** outputs/agent_video_run.log (first simulation), outputs/agent_video_run2.log (smooth pan)
**Fix or mitigation:** (1) accepted: ~6 % of a candidate's OpenCV time (re-analysis 104-178 s). (2) Geometry is refused if any of line fit, motion, zoom or cut fails, so line fit alone is not trusted. Real pan/zoom cameras (perspective change, partial pitch) would also fail the line fit; not testable without such a clip.
**Measured impact:** quality check 8.0-12.6 s (real windows), 17.8 s (simulated pan).

### [2026-10-15] Agent spike: the model's free text can contradict the tool results it cites
**Stage:** agent
**Severity:** wrong output (text only; every decision was right)

**Input:** build step 4 spike, Nova 2 Lite (`global.amazon.nova-2-lite-v1:0`), the 10 candidates of dev seed 45, synthetic backend (`scripts/spike_agent.py --seeds 45`).
**What happened:** all 10 decisions matched the rules arm, with valid citations and clocks, but the text is not always true. (1) evt_005 was rejected because the shape **reverted** after 35 s (rules verdict), yet its recorded reason says "Re-analysis shows no revert". (2) The alert for evt_004 (3-5-2 -> 3-4-3: one midfielder fewer, one forward more) suggests "exploit the extra midfield player". (3) Several reasons say "held for 20 s": that is the engine's persistence rule, not the 60 s look-ahead that was checked. (4) On 5 of 6 confirmed candidates the model called `render_evidence` before `record_decision` (blocked by the guard, one wasted call each); one reason exceeded 200 characters (rejected as invalid arguments).
**Why (best guess):** grounding checks that refs exist and that clocks fall inside cited windows; it does not check what the sentence claims (number matching was cut on 15 Oct). The verdict's own numbers (share held, revert time) are in the tool results but the small model paraphrases loosely, and the line-by-line difference ("midfield 5->4, front line 2->3") is only in the card.
**Screenshot / output:** outputs/spike/spike_20261015T120444.json, outputs/spike/trace_20261015T120444.jsonl, outputs/spike/alerts_llm_20261015T120444.jsonl
**Fix or mitigation:** open (step 4 is a measurement). Options: show the rules verdict's reason (code-written, always true) as the primary reason in the UI and the model's text as the explanation; put the line-by-line difference and the look-ahead numbers into the `record_decision` / `propose_alert` context; a `next` hint in the rules block to stop the render-before-decide call.
**Measured impact:** 10 / 10 decisions right vs the rules arm; 1 of 10 reasons contradicts its verdict; 1 of 6 suggestions is tactically wrong; 5 guard blocks + 1 invalid call in 38 LLM calls.

### [2026-10-15] Validation seeds 100-109: 4-3-3 <-> 4-2-3-1 flips that last over a minute become false alerts
**Stage:** agent (rules verifier)
**Severity:** wrong output (known limitation)

**Input:** rules arm with the thresholds frozen on dev, seeds 100-109 (validation, never tuned on; `scripts/eval_agent.py --set val`).
**What happened:** false alerts 52 -> 19 and alerted real changes 31 -> 28 (3 real changes uncertain, none rejected). 14 of the 19 remaining false alerts are 4-3-3 <-> 4-2-3-1 flips, 12 of them in seeds 104 and 105, the two matches already known for this (FAILURE_LOG 2026-10-10).
**Why (best guess):** the persistence/revert checks only see 60 s after detection. When a team spends more than a minute in its out-of-possession shape (wide forwards dropped), the new label holds for the whole look-ahead and no reverse candidate appears inside it.
**Screenshot / output:** outputs/eval_agent_val.json
**Fix or mitigation:** not tuned (validation data). The same fix as before would help: classify in- and out-of-possession shapes separately (needs the ball). Seed 111 of the final set has 16 such flips, so this is the main risk for the final bar (false alerts <= 16).
**Measured impact:** 14 of 19 validation false alerts.

### [2026-10-15] A hard coverage gate in the verifier blocked a third of the real changes
**Stage:** agent (rules verifier, build step 1)
**Severity:** wrong output (caught on dev data, fixed before validation)

**Input:** rules arm with the design rules, dev seeds 42-52 (`scripts/eval_agent.py --set dev`).
**What happened:** with "coverage >= 0.6 before and after, else no verdict", the rules arm cut false alerts from 27 to 1 but left **13 of 39 real changes uncertain**: changes made around a broadcast-window stretch, where the team is partly off-screen just before or after. All 13 had >= 4 confident look-ahead windows, almost all with 100 % in the new shape.
**Why (best guess):** double counting: a window is only confident when >= 8 outfield players are visible in enough of its frames, so persistence over confident windows already accounts for visibility. Coverage measured over all frames punishes the honest gaps a second time.
**Screenshot / output:** outputs/eval_agent_dev.json (before/after in this entry; reasons per candidate in the file)
**Fix or mitigation:** coverage now asks for a second look (`need_more`) but never blocks a verdict once that look is done. Persistence thresholds were then chosen on dev by a fixed rule (most alerted hits minus false alerts): `persist_pass` 0.7 -> 0.6, `min_confident_windows` 4 -> 3 (63 of 81 grid settings pass the step-1 gate).
**Measured impact (dev):** alerted real changes 25 -> 37 (design thresholds) -> 39 of 43 (frozen), false alerts 1 -> 4 -> 4.

### [2026-10-15] `line_drop`: an absolute line-height rule measures the phase of play, not a tactical drop
**Stage:** change detection (`line_drop` events)
**Severity:** wrong output (feature implemented, switched off by default)

**Input:** synthetic dev set (match_001 + seeds 43-52) and held-out seeds 110-119; TeamTrack top and side clips, pipeline vs oracle (`scripts/tune_line_drop.py`, `scripts/plot_line_levels.py`).
**What happened:**
1. **No ground truth.** Synthetic GT cannot label a line drop without changing the frozen contract (`GTNoiseEvent.kind` is a closed list), and the generator never drops a line on purpose: its back line follows the ball and possession (`back_line_ball_gain`). Every synthetic `line_drop` is therefore a false alarm for a tactical drop; recall cannot be measured.
2. **The rule fires on ball movement.** Rule: the 30 s trailing defensive line sits â‰¥ X m deeper than its reference for â‰¥ Y s (causal, same hysteresis as shape changes). On the dev set the 30 s line level moves a median **10.5 m per minute** (p90 27 m). No setting of X âˆˆ {4..12} m Ã— Y âˆˆ {30..180} s met the budget of â‰¤ 1 false alarm per match fixed before the sweep; the fewest was 12 m / 180 s with **1.55 per match** (dev), **1.70 per match on seeds 110-119**.
3. **Real footage is worse.** On the drone clips the home line moves from 57 m to 19 m from its goal in 40 s (1610-1650 s): real lines follow play far more than the generator's. With 12 m / 180 s nothing fires in 4 minutes; with looser settings (8 m / 60 s, 4 m / 30 s) events appear, but at the moments when play moves into a team's half.
4. **Perception is not the problem.** On the drone view the pipeline's line level follows the oracle's within ~1 m, and at every threshold the pipeline fires exactly the same events as the oracle, at the same times (4/4 at 4 m / 30 s). On the side view the pipeline is uncertain in 2/3 of the windows, so there is little to compare.
**Why (best guess):** a defensive line "dropping" is only meaningful *for a given ball position*: a team that sits deeper when the opponent has the ball in midfield. The rule would need to condition on the ball and on possession, and the pipeline does not see the ball on the drone view (entry below).
**Screenshot / output:** outputs/failures/2026-10-15_line_drop_levels_top.png (pipeline vs oracle line level), outputs/failures/2026-10-15_line_drop_levels_side.png; outputs/tune_line_drop_dev.json
**Fix or mitigation:** implemented (`tactics/events.py: line_levels, detect_line_drops`, tested) and **switched off by default** (`tactics.line_drop.enabled: false`, thresholds kept at the dev choice 12 m / 180 s): with no measurable benefit it only adds false candidates for the agent. To revisit once the pipeline sees the ball: measure the line only when the opponent has the ball in the middle third.
**Measured impact:** 1.70 false line-drop candidates per match on held-out seeds when enabled; 0 events on the real clips at the configured setting.

### [2026-10-15] Treating 4-3-3 and 4-2-3-1 as one family for change detection loses real changes
**Stage:** change detection
**Severity:** trade-off (measured, switched off)

**Input:** `formations.change_equivalent: [["4-3-3", "4-2-3-1"]]` (change detection only; labels, confidences and segments keep the exact formation), synthetic dev set (match_001 + 43-52) and new held-out seeds 110-119, with and without (`--no-change-equivalence`).
**What happened:**

| | dev 42-52 without | dev with | **held-out 110-119 without** | held-out with |
|---|---|---|---|---|
| hits / true changes | 39 / 43 | 36 / 43 | **34 / 38** | 28 / 38 |
| false positives | 27 | 18 | **34** | 16 |
| of which 4-3-3 â†” 4-2-3-1 | 11 | 0 | 18 (16 in seed 111) | 0 |
| mean detection delay | 41.1 s | 41.5 s | 42.1 s | 39.6 s |
| timeline max | 7.9 KB | 8.2 KB | 14.6 KB | 6.6 KB |

The family removes every pair flip-flop, but **all 6 hits it loses on held-out (3 on dev) are real 4-3-3 â†” 4-2-3-1 switches**, which become invisible by construction. Unlike 3-5-2 = 5-3-2 (no hits lost on 100-109), this is not free.
**Why (best guess):** single vs double pivot is a genuine tactical change a coach wants to hear about (the 10 Oct entry already argued this), and the synthetic schedule switches between these two as often as between any other pair.
**Screenshot / output:** outputs/eval_synthetic_heldout2_nocheq.json vs outputs/eval_synthetic_heldout2_cheq.json (and the dev pair)
**Fix or mitigation:** **off by default** (`change_equivalent: []`): the Phase 3 agent can reject a false candidate, but it can never recover a change the detector did not emit. The mechanism stays (one config line) in case the user prefers fewer, safer candidates. Better fix for later: classify in- and out-of-possession shapes separately (needs the ball, see the ball entry).
**Measured impact:** see table; real TeamTrack clips unchanged either way (no 4-3-3 / 4-2-3-1 windows in them).

### [2026-10-15] The pipeline never sees the ball on the drone view: no possession, no pressing
**Stage:** detection
**Severity:** degraded (open)

**Input:** saved pipeline MatchStates (`outputs/match_state_top_4fps.json`, 540 frames; `match_state_side_2fps.json`, 240 frames), found while designing `line_drop` (step 6).
**What happened:** the drone pipeline outputs a ball in **0 of 540** frames, so `possession` is null everywhere and the timeline's `possession_pct` and `pressing_index` are always null on real top-view output. The side pipeline has a ball in 10 of 240 frames (possession in 3). The oracle has the GT ball in 533 of 541 top frames.
**Why:** the top-view detector is the classical blob detector, built for players: a ball is ~0.22 m across (~6 px at drone scale), far below its `min_area_m2: 0.12`, and nothing else looks for it. On the side view the COCO "sports ball" class of YOLOX fires rarely on 9Ã—9 px balls.
**Screenshot / output:** counts above (no image: the failure is an absence)
**Fix or mitigation:** open. Consequences, stated where they matter: (1) `line_drop` cannot condition on the ball (it would be the natural way to separate "the team sits deeper" from "the ball is in their half", see the line_drop entry); (2) the Phase 3 agent cannot use `possession: dead` or the ball position to recognise set pieces on real footage; (3) pressing and possession are not compared in `eval_real.py`. Options: a small-blob + motion ball detector on the drone view, or a ball-specific ONNX model in `cv2.dnn`.
**Measured impact:** possession / pressing missing in 100 % of top-view pipeline frames.

### [2026-10-15] Re-tuning team colours on GT crops picked settings that put officials into the teams
**Stage:** team colour (tuning method)
**Severity:** wrong output (caught on dev data, fixed before any eval run)

**Input:** dev clips only (top D_â€¦_1530, side F_â€¦_1680), `scripts/tune_teams.py`, re-choosing `teams.l_weight` / `teams.gate` without eval data (they had been chosen with eval data on 14 Oct).
**What happened:** the first version scored per-crop accuracy on **GT boxes** and chose `l_weight 1.0, gate 3.5` (98.5 % vs 94.8 % for the old setting). Running the pipeline on the dev clips with it, the drone view had **2.0 unmatched detections per frame labelled home/away** (officials and staff in a team colour). Re-scored on the pipeline's own **detection crops**, the same setting keeps only 41 % (top) / 25 % (side) of the non-player crops out of both teams.
**Why:** GT has no officials, so a GT-crop score rewards wider gates (every player fits) and never sees the people the gates exist to keep out. A first guard (keeper crops must stay outside the gates) passed on GT crops; fitted on the detection crops, which include the officials and shift the team centres, the same setting also swallows half the keeper crops.
**Screenshot / output:** outputs/tune_teams_dev.json (detection-crop grid), outputs/tune_officials_dev.log
**Fix or mitigation:** the score is now 3-class accuracy on the pipeline's dev detection crops: matched outfield player -> their team, matched keeper and every unmatched detection -> "other". Chosen `l_weight 0.75, gate 2.0` (ties within 0.1 % go to the smaller gate; gate 1.5 is worse, so 2.0 is an interior optimum).
**Measured impact (dev):** non-player crops kept out of the teams 41 % / 25 % (1.0 / 3.5) -> 99 % / 80 % (0.75 / 2.0); outfield crops given the right team 96 % / 97 % -> 93 % / 96 % (crop level, before the per-track vote); team-labelled phantoms on the top dev clip 2.0 -> 0.0 per frame. Eval-clip numbers: CLAUDE.md Key numbers.

### [2026-10-15] Pan/zoom camera: not supported
**Stage:** camera motion / homography
**Severity:** known limitation (out of scope; `perception/camera_motion.py` was cut on 14 Oct)

**Input:** the hard-mode clip "2019-11-10: U13 CCL VLSC vs SOCA" by the YouTube channel *Bil Kleb* (CC BY), https://www.youtube.com/watch?v=3vxIlarKxjw, looked at by eye at **0:05, 0:40 and 1:30**. No pipeline run.
**What is visible:** 0:05 â€” kickoff, camera zoomed onto the centre circle and halfway line, a handful of players, spectators on the far touchline; 0:40 â€” camera panned to one goal: the goal, one corner of the penalty box and part of the arc, a few players running towards it; 1:30 â€” camera near a corner flag, about a third of the pitch, faint white lines crossed by darker lines of other pitch layouts painted on the same grass.
**What happened:** nothing in Gaffer's geometry holds for this camera:
1. **Only part of the pitch is ever visible.** At 0:05 (kickoff) the view is zoomed onto the centre circle and halfway line: no goal line, penalty box or corner, ~6 players in view. At 0:40 it has panned to one goal (goal, one penalty-box corner, a sliver of the arc), at 1:30 to a corner flag. A homography needs â‰¥ 4 known pitch points in the frame, spread out; most frames show one marking (a circle, a line, part of a box) and many players are off-screen, so even a perfect frame gives < 8 of 10 outfield players (`tactics.min_players`) most of the time.
2. **The lines are faint and ambiguous.** The white paint is worn and thin at this distance, and the grass carries dark lines from other pitch layouts painted over the same field (visible at 0:40 and 1:30), so a line mask finds markings that belong to no model of *this* pitch. The TeamTrack drone and side calibrations relied on crisp lines (FAILURE_LOG 2026-10-10).
3. **The homography would change every few seconds.** The camera pans to follow the ball and zooms in and out, so the image-to-pitch mapping must be re-estimated on every frame. Our per-frame re-anchoring (`perception/drift.py`) corrects a few pixels of drone wobble around one fixed calibration; it cannot follow a 90Â° pan or a 2Ã— zoom, and with one marking in view there is nothing to re-anchor to.
**Why (best guess):** a single amateur camera that follows the ball is the common grassroots setup, but it needs a different approach: per-frame keypoint detection of pitch landmarks (a trained model) plus camera-motion tracking between landmark sightings, and formations only when most of a team is in view. That is a project of its own.
**Screenshot / output:** none, by design. The players are minors (U13) and we do not hold the original file (the owner was asked for it; DATA_SOURCES), so no frame of this video is committed or redistributed; this entry describes it in words only. Anyone can check it at the timestamps above.
**Fix or mitigation:** known limitation, stated in the README and report: Gaffer needs a **fixed or near-fixed camera that shows the whole pitch** (drone or fixed panorama, like TeamTrack). Phase 3's `check_frame_quality` should report a camera that moves as "homography not ok" rather than guess.
**Measured impact:** not run: the pipeline has no calibration for this camera, and none would hold beyond a few seconds.

### [2026-10-14] Side view: the near assistant referee is output as a 12th "away" player
**Stage:** team colour
**Severity:** wrong output (fixed 15 Oct)

**Input:** side eval clips 1710â€“1800 s at 2 fps (`py scripts\eval_tracking.py --view side --whole-source --save`); found by rescoring the saved `outputs/match_state_side_2fps.json`.
**What happened:** the assistant referee on the near touchline (dark navy tracksuit, flag) is detected and tracked as one track for the whole window, and labelled **away in 173 of 180 scored frames**. They stand 0.3â€“0.8 m outside the touchline, which the contract keeps (5 m off-pitch tolerance, for throw-ins), so the formation engine would see 11 away outfield players. They are all of the unmatched "away" detections that lie > 10 m from any GT player (173 of 251 with the GT margin removed). The dev clip shows a similar rate (1.4 unmatched "away" per frame) and it was not noticed there.
**Why (best guess):** dark navy is close to the away team's dark blue; the classifier down-weights lightness (`teams.l_weight` 0.5), which is where the two differ most. On the drone view the officials' kit falls outside both team gates and they become referees; from the side the near official is large and seen mostly against grass.
**Screenshot / output:** outputs/failures/2026-10-14_side_touchline_person_as_away.jpg
**Fix or mitigation:** fixed 15 Oct by a geometric rule (user decision): a track beyond a touchline for â‰¥ 75 % of its life is an official (`perception.official`, `pipeline.official_tracks`; thresholds chosen on the dev clips only with `scripts/tune_officials.py`, no GT player flagged on either dev clip). Independently, the team-colour settings were re-chosen on dev clips (`l_weight 0.75`, `gate 2.0`), which by themselves keep more officials out of the teams.
**Measured impact:** a phantom away player in 96 % of side eval frames before; after: of the 178 eval detections beyond the near touchline, **173 are "referee"** (the assistant referee) and 5 "home"; unmatched detections labelled "away" 47 % â†’ 22 %; side precision with referee-labelled detections removed 0.831 â†’ 0.888 (raw precision 0.794 unchanged: it counts every output detection).

### [2026-10-14] Spare balls behind a goal are tracked as a "home" player
**Stage:** detection / team colour
**Severity:** wrong output (caught by eval, mitigated)

**Input:** drone view, 270 s run at 2 fps (`py scripts\eval_tracking.py --view top --whole-source`), after the keeper fix below.
**What happened:** a small heap of white spare balls ~1 m behind the goal line forms one blob of player size for the classical detector. It is white, like the home shirts, so its track voted "home" and was output as a home outfield player in **198 frames**. It also competed for the goal's keeper slot (see the entry below).
**Why (best guess):** the top-view detector finds non-grass blobs of player size and has no notion of a person; GT has no label for objects, so the blob only shows up as an unmatched "home" detection.
**Screenshot / output:** outputs/failures/2026-10-14_static_spare_balls_home.jpg
**Fix or mitigation:** a track that stays within 0.3 m (95th percentile of its distance from its median position) for 20 s or more is an object, not a person, and is dropped from the output (`perception.static_object`). Thresholds chosen after seeing this case in the eval run. Known risk: a player who stands perfectly still for 20 s+ (e.g. a long stoppage) would be dropped too. Shrinking the search region does not help: it reaches 1 m behind the goal line (`detector.views.top.roi_margin_goal_m`) so that keepers on the line are found, and the balls lie just inside it.
**Measured impact (top eval clips 1560â€“1800 s, 2 fps):** 0.32 static detections removed per frame; unmatched detections labelled "home" fell from 0.43 to 0.12 per frame (the same amount), so the filter removed objects, not players; raw precision 0.843 â†’ 0.852. The same run's recall fell 0.976 â†’ 0.955 for an unrelated reason: the scorer now counts only what the pipeline outputs, and at 2 fps 0.51 detections per frame never get a track id (0.07 at 4 fps).

### [2026-10-14] Pipeline got the attacking direction backwards, so both keepers got the wrong label
**Stage:** team colour / goalkeepers
**Severity:** wrong output (caught by eval, fixed)

**Input:** drone view, full 270 s run at 2 fps (`py scripts\eval_tracking.py --view top --whole-source`), first version of the keeper logic.
**What happened:** the pipeline inferred "home attacks right"; the oracle (and the keepers' positions) say home attacks left. Consequences: the home keeper (red) was labelled **away goalkeeper in 468 frames**, i.e. every keeper label had the wrong team (`goalkeeper_team_correct` 0.00), and the away keeper (yellow) was labelled **referee in 476 frames**. Settled team accuracy was 0.907 instead of ~0.95.
**Why:** (1) the direction rule (shared with the oracle) compared each team's median distance from its deepest player to each goal line. It relies on the keeper; in the pipeline keepers are only identified *after* the direction is known (their shirts are "other" colours), so it ran on outfield players only, and over this 4.5 min stretch the home attack sat deep in the opponent half. On the 30 s smoke-test window it happened to be right. (2) The keeper slot of a goal went to the "other" track nearest the goal line: spare balls and staff just behind the line beat the yellow keeper.
**Screenshot / output:** outputs/failures/2026-10-14_direction_inverted_keepers.jpg (home keeper boxed as "GK20" in the away colour)
**Fix or mitigation:** (1) direction by a per-frame vote on whose rearmost player is nearer each goal (the offside line keeps attackers behind the last defender, keepers not needed); it gives the same answer as before on both oracle files, and the right answer on the pipeline labels and on the oracle with its keepers removed. (2) A keeper candidate's median position must be on the pitch side of the goal line, and the longest track wins the slot. (3) After (1)+(2) the home keeper was right in every frame, but the away keeper was still "referee": their median position over the run was **20.6 m** from the goal line (they play far off the line), just outside the 20 m keeper zone. The zone was widened to 30 m; referee track medians were â‰¥ 39 m from both goal lines. This threshold was chosen after seeing eval-clip data.
**Measured impact:** drone view at 2 fps after (1)+(2): settled team accuracy 0.907 â†’ 0.957, keeper team right 0.00 â†’ 1.00; final numbers after (3) in CLAUDE.md.

### [2026-10-14] Tracking at 2 fps: ByteTrack fragments tracks and swaps ids between nearby players
**Stage:** tracking
**Severity:** degraded

**Input:** dev clips only (top D_â€¦_1530, side F_â€¦_1680), `supervision` ByteTrack on the pipeline's detections, ids compared with TeamTrack PlayerIDs at the 2 fps output frames (`scripts/eval_tracking.py`; sweeps on cached detections).
**What happened:** (1) out of the box (boxes enlarged 3Ã—, detector scores passed through) the drone dev clip had **122 ID switches in 30 s for 22 players** (11 per player-minute), IDF1 0.39, 98 tracks: at 2 fps a player moves up to ~4 m (~120 px) between samples, so even 3Ã— boxes stop overlapping. (2) ByteTrack multiplies IoU by the detection score, and the classical detector's "score" is a blob-area ratio, not a confidence: partial blobs never matched. (3) `update_with_detections` maps tracks back to detections by IoU of the Kalman box; with large boxes neighbours overlap, so this step is ambiguous (replaced by centre distance). (4) The remaining switches are swaps between players within 2â€“4 m of each other (27 of 40 within 2 m on the dev clip): a tackle merges two blobs, and when they part the 0.5 s gap is too long to tell who is who.
**Why (best guess):** IoU association assumes overlap between consecutive frames; 2 fps breaks that for fast, small, look-alike objects.
**Screenshot / output:** outputs/failures/2026-10-14_tracking_swap_2fps.png (a tackle at 1535.5 s reshuffles tracks 5 and 12)
**Fix or mitigation:** matching boxes enlarged by 1 + 12 / fps (7Ã— at 2 fps, 3Ã— at 6 fps), unit scores for association, centre-distance mapping back; tracking at a higher rate than the output (an integer multiple of 2 fps; 5 fps does not land on the 0.5 s output grid, so 4 and 6 fps were measured). The tactics engine never reads track ids: switches only matter through the per-track team vote, so team accuracy decides what is acceptable.
**Measured impact (dev clips):** top: 122 â†’ 41 switches at 2 fps (IDF1 0.39 â†’ 0.71), 24 at 4 fps (0.80), 17 at 6 fps (0.86); side: 42 at 2 fps (IDF1 0.64), 30 at 6 fps (0.71). Eval-clip numbers: see Key numbers in CLAUDE.md.

### [2026-10-14] Side view: a 1 m score mostly measures how the annotator drew the box bottom
**Stage:** detection (evaluation)
**Severity:** degraded (metric), no pipeline output affected

**Input:** TeamTrack side clips, GT boxes vs. the lowest moving-player pixel (temporal-median background of 30 frames per clip, 566 isolated boxes); `py scripts\compare_detectors.py --view side`.
**What happened:** TeamTrack side boxes end **2â€“3 px below the feet** (median 2 px on the far side, 3 px in the middle and near rows; boxes are also ~3â€“7 px loose at the top). On the far side one pixel row is 0.4â€“1 m of pitch depth, so the GT foot point sits ~1 m nearer the camera than the player. A correct detection with a tight box then misses the 1 m criterion. The size of the effect differs between clips: on the dev clip YOLOX boxes ended where GT boxes end (moving GT up 2.5 px made far-half F1 slightly worse, 0.59 â†’ 0.56), on the three eval clips they ended ~2.5 px higher (F1@1 m 0.49 raw â†’ 0.75 with GT moved up 2.5 px; far half 0.32 â†’ 0.63).
**Why (best guess):** hand-drawn boxes with a margin, possibly a different annotator or tool setting per clip; far-side depth resolution of a low panorama camera (see the 10 Oct side-geometry entry).
**Screenshot / output:** outputs/failures/2026-10-14_side_gt_box_margin.png; outputs/compare_detectors_side.json (`+inset` rows)
**Fix or mitigation:** report raw scores (as specified) and, labelled, scores against the GT foot point moved up by the measured margin (`teamtrack.views.side.gt_foot_inset_px: 2.5`, eval only); report the near and far halves separately and add a 2 m column. The oracle still uses the raw box bottom (unchanged since Day 1). Open question for step 5: on the eval clips the YOLOX foot points sit ~2.5 px above the GT ones, i.e. far-side pipeline positions lie up to ~1 m deeper than the oracle's, which will show up as metric error (defensive line, width) unless the oracle also uses the inset.
**Measured impact:** YOLOX F1 at 1 m on the eval clips: 0.49 raw vs 0.75 with the margin removed; at 2 m: 0.78.

### [2026-10-14] Side view: background subtraction loses standing, overlapping and camouflaged players
**Stage:** detection
**Severity:** wrong output (rejected method)

**Input:** side eval clips 1710â€“1800 s, 150 frames at 2 fps, `cv2.createBackgroundSubtractorMOG2` on the pitch band, blobs filtered by expected person size from the mapper's ground scale; tuned on the dev clip only.
**What happened:** three failure types (2 m criterion, dev clip): (1) players standing still for a while are learnt into the background (15 s history: 102 misses; 60 s history fixed most of it, F1@1 m 0.42 â†’ 0.48); (2) two players at different depths overlap in the image and form one tall blob whose foot point is the nearer player's; (3) a white shirt in front of the white fence/stands, or a lost leg, gives a blob whose foot point is > 2 m off. On the eval clips: F1 at 1 m **0.29** (near half 0.47, far 0.12), at 2 m 0.56, 17.8 unmatched boxes per frame â€” versus tiled YOLOX 0.49 / 0.78 at 1 m / 2 m.
**Why (best guess):** a static-camera background model sees motion, not people; the side view has 0.47 overlapping player pairs per frame (DATA_NOTES), and far players are 14 Ã— 24 px.
**Screenshot / output:** outputs/failures/2026-10-14_side_background_misses.png; outputs/compare_detectors_side.json
**Fix or mitigation:** tiled YOLOX (cv2.dnn) stays the side-view detector (`detector.views.side.method`); MOG2 stays selectable as a 22Ã— faster fallback (156 ms vs 3.4 s per frame).
**Measured impact:** F1 at 1 m 0.29 (MOG2) vs 0.49 (YOLOX); at 2 m 0.56 vs 0.78.

### [2026-10-10] Top-view classical detector: players on painted lines and touching pairs are missed; referees count as false positives
**Stage:** detection
**Severity:** degraded

**Input:** TeamTrack top view, `py scripts\compare_detectors.py --view top` (8 eval clips, 48 frames; dev clip D_â€¦_1530_1560 used for tuning only).
**What happened:** (1) The first version masked out the projected painted lines; players standing on a line (white shirts are paint-coloured) lost their pixels and disappeared: 6 of the 8 misses in a sample were players on lines. (2) Two players touching (e.g. a tackle) give one blob below the split threshold â†’ one detection between them, matched to neither. (3) The first ROI (3 m beyond the touchlines) picked up the painted "University of Tsukuba / IMAGINE THE FUTURE" text, corner flags and goal frames: 43 extra blobs per frame on the dev clip. (4) The remaining ~4 unmatched detections per frame are real people GT does not label: on the pitch it is the referee in every inspected case, outside the lines the assistant referee and staff (3.0 of the 4.0 per frame are outside the lines).
**Why (best guess):** colour cannot separate a white shirt from white paint; area alone cannot separate two touching players from one large one; GT contains only the 22 players.
**Screenshot / output:** outputs/failures/2026-10-10_top_classical_misses.jpg (misses before the line fix), outputs/failures/2026-10-10_top_classical_extras_on_pitch.jpg (all the referee)
**Fix or mitigation:** (1) "lines are thin, players are wide": inside the projected line band only foreground that survives a 0.4 m morphological opening is kept, and blobs lying â‰¥ 97 % inside the band (crossing remnants) are dropped; (3) geometric exclusions from the homography: 1 m margin beyond the lines, corner-flag squares, goal-frame strips. (2) open; (4) the team classifier (Day 2) puts referees in their own cluster, and eval reports them separately.
**Measured impact:** dev clip precision 0.33 â†’ 0.84 (ROI exclusions); eval recall 0.966 â†’ 0.978 (line opening), precision 0.843, F1 0.906, isolated-player recall 0.991.

### [2026-10-10] Off-the-shelf YOLOX stays useless on the drone view even tiled at native resolution
**Stage:** detection
**Severity:** wrong output (rejected method)

**Input:** same 8 eval clips; YOLOX-S (COCO) in `cv2.dnn` on overlapping 640 px tiles over the pitch, cross-tile NMS; 12 frames.
**What happened:** recall at 1 m: **0.06** (confidence 0.3), 0.14 (confidence 0.1), **0.54** with tiles upscaled 2Ã— â€” at 5.0 s, 5.1 s and 18.1 s per 4K frame on the laptop CPU. The classical OpenCV detector reaches 0.978 recall at 0.08 s per frame.
**Why (best guess):** seen from directly above a player is a ~30 px blob without a human silhouette (Phase 0 entry); upscaling helps a little but the shape is still not a COCO "person".
**Screenshot / output:** outputs/failures/2026-10-10_top_yolox_vs_classical.jpg; numbers in outputs/compare_detectors_top.json
**Fix or mitigation:** classical detector chosen for the top view (config `detector.views.top.method`). Fine-tuning YOLOX was not needed. YOLOX stays the side-view detector, where players look like people.
**Measured impact:** F1@1 m 0.11 / 0.24 / 0.65 (YOLOX variants) vs 0.906 (classical), 60â€“220Ã— slower.

### [2026-10-10] The drone wobbles within a clip: one homography per clip is not enough
**Stage:** homography
**Severity:** degraded

**Input:** all 9 top clips, frames at 0 / 10 / 20 / 29.5 s, `py scripts\eval_drift.py`.
**What happened:** the image moves up to ~14 px relative to the calibration frame, and not only between clips: within one clip it shifts by up to ~10 px back and forth. Anchoring once per clip (at its first frame) is sometimes *worse* than no correction at all (e.g. 1690 s: 0.37 m anchored per clip vs 0.22 m uncorrected), because the drone swings back past the reference.
**Why (best guess):** a hovering drone, not a locked camera; wind.
**Screenshot / output:** outputs/failures/2026-10-10_drone_drift.png; outputs/eval_drift_top.json
**Fix or mitigation:** re-anchor **every sampled frame** (`perception/drift.py`: line image â†’ `cv2.phaseCorrelate` â†’ `cv2.findTransformECC` affine, ORB + `estimateAffinePartial2D` fallback), ~125 ms per frame. Caveat: the line-alignment error is measured on the same painted lines the alignment uses, so it shows consistency with the lines, not independent ground truth.
**Measured impact:** median pitch-line alignment error over 36 sampled frames: **0.198 m** uncorrected â†’ 0.089 m anchored per clip (p90 0.268 m) â†’ **0.040 m** anchored every frame (p90 0.047 m, = the calibration frame's own 0.041 m); max shift 13.8 px; 142 ms per frame.

### [2026-10-10] Top and side TeamTrack clips with the same time in their names are not simultaneous
**Stage:** homography (cross-view check) / data
**Severity:** wrong assumption (no output affected yet)

**Input:** `D_20220220_1_1680_1710` (drone) vs `F_20220220_1_1680_1710` (side), GT boxes mapped to pitch metres with both Phase 2 calibrations.
**What happened:** at nominal t = 1680 s the drone's 22 players are all in the right half while the side camera's are attacking the left goal; team centroids differ by ~35 m. A search over every time offset from âˆ’270 to +120 s, four orientation hypotheses (drone rotated 180Â°, not rotated, mirrored in x, mirrored in y) and three team mappings (same, swapped, ignored) never brings the two views closer than **14 m** mean matched-player distance; a genuine match should be ~2 m (the drone against itself 0.5 s later: 1.8 m).
**Why (best guess):** the file names carry each camera's own clip time, not a shared match clock (or the files come from different parts of the recording). DATA_NOTES inferred the overlap from file names only.
**Screenshot / output:** outputs/failures/2026-10-10_views_not_simultaneous.png
**Fix or mitigation:** DATA_NOTES corrected; the cross-view consistency check is dropped (there is no simultaneous pair in our files). Both views are evaluated independently against their own GT. The drone's 180Â° orientation therefore rests on within-view evidence only (keeper sides, assistant referee on the near touchline, upside-down text); it is a convention inside the top view's MatchState and does not affect any metric.
**Measured impact:** cross-view comparison not possible with the downloaded files.

### [2026-10-10] Side panorama: stitching ghost at the edges, far-side geometry only good to ~1â€“2 m
**Stage:** homography
**Severity:** degraded

**Input:** `F_20220220_1_1680_1710.mp4` frame 0, side calibration.
**What happened:** (1) at the near-right corner the goal line appears **twice**, ~12 px apart, with green/magenta fringes: a stitching seam (the left edge is similarly smeared). (2) On the far side, lines are 1â€“2 px thin and meet at grazing angles, and one image row spans 0.5â€“1 m of depth: automatic snapping slid landmarks 8â€“115 px along the lines, so on the side view 18 of 29 landmarks keep their hand-picked positions (snaps capped at 6 px). Held-out error is worst on far landmarks (`half_far` 1.77 m, `pa_L_goal_far` ~1.0 m) vs 0.2â€“0.5 m near the camera. The near ends of both penalty arcs cannot be located at all (arc and box line merge) and are excluded.
**Why (best guess):** a ~6500 px panorama of a 105 m pitch from a low camera: far-side depth resolution is inherently coarse, and stitching seams break line continuity.
**Screenshot / output:** outputs/failures/2026-10-10_side_stitching_ghost.jpg; per-landmark errors in `data/calibration/side_model_comparison.json`
**Fix or mitigation:** known limitation; per-frame `reprojection_error_m` and the far-side uncertainty will be reported with the side-view results. The top view (0.11 m) stays the primary geometry.
**Measured impact:** side held-out landmark error mean 0.53 m, max 1.77 m (top view: mean 0.11 m, max 0.38 m).

### [2026-10-10] The "fisheye" side view is not a fisheye: `cv2.fisheye` loses to plain homographies
**Stage:** homography / undistortion
**Severity:** wrong model (caught before use)

**Input:** side reference frame, 29 landmarks, five candidate models compared by leave-one-out landmark error (`py scripts\calibrate.py --view side`).
**What happened:**

| model | held-out mean | median | max | line error median / p90 |
|---|---|---|---|---|
| **sectioned homographies, 2 sections (split at halfway)** | **0.53 m** | 0.43 m | 1.77 m | 0.08 / 1.23 m |
| sectioned, 4 sections | 0.58 m | 0.49 m | 1.77 m | 0.10 / 1.23 m |
| single homography | 0.60 m | 0.51 m | 2.31 m | 0.09 / 1.19 m |
| `cv2.fisheye` (K, k1..k4, pose) | 0.86 m | 0.79 m | 2.26 m | 0.08 / 1.18 m |
| cylindrical camera | does not fit (fit rms 21 m) | | | |

`cv2.fisheye.calibrate` refused the single planar view; the least-squares fit on `cv2.fisheye.projectPoints` only works by becoming physically implausible (fy/fx = 0.32, camera 22.6 m high, 2.3 m from the touchline), i.e. by imitating a homography, and its "undistorted" image is nearly identical to the input. The cylindrical model predicts a near touchline curving up ~350 px at the edges; the real one is straight.
**Why (best guess):** the panorama behaves like one very wide **rectilinear** image looking straight across the pitch: every line parallel to the touchlines is a horizontal image row (near touchline at 882â€“895 px over the full 6500 px), goal lines converge to the centre, the halfway line is vertical. That is pinhole geometry, which a homography represents exactly; the remaining errors come from stitching seams, which sections absorb.
**Screenshot / output:** outputs/failures/2026-10-10_side_panorama_model_comparison.jpg (bird's-eye rectifications); all images in outputs/calibration/ (`side_original.jpg`, `side_overlay_<model>.jpg`, `side_birdseye_<model>.jpg`, `side_fisheye_undistorted.jpg`)
**Fix or mitigation:** use sectioned homographies (chosen automatically by held-out error); `cv2.fisheye` stays in `undistort.py` as a measured baseline.
**Measured impact:** held-out landmark error 0.86 m (fisheye) â†’ 0.53 m (sectioned).

### [2026-10-10] Held-out check: 4-3-3 â†” 4-2-3-1 flip-flops double the false positives; timeline exceeds 8 KB
**Stage:** formation / change detection (honesty check on Phase 1)
**Severity:** wrong output (candidates only)

**Input:** 10 fresh synthetic matches, seeds 100â€“109 (never used for tuning or eval before), run with the Phase 1 engine **unchanged**, once with and once without `formations.equivalent: [["3-5-2", "5-3-2"]]`. Run via a temporary config copy (`eval.synthetic.dev_seeds = 100..109`, `--dev`), outputs `outputs/eval_synthetic_heldout.json` and `outputs/eval_synthetic_heldout_noeq.json`.
**What happened:**

| held-out seeds 100â€“109 | with equivalence | without |
|---|---|---|
| formation accuracy when confident (exact) | 97.0 % | 97.0 % |
| coverage (confident windows) | 79.3 % | 79.1 % |
| strict accuracy (uncertain = wrong) | 76.9 % | 76.8 % |
| shape changes: hits / true | 31 / 36 | 31 / 36 |
| misses (found late after low visibility) | 5 (4) | 5 (4) |
| **false positives** | **52** | 67 |
| mean / max detection delay | 51.4 s / 105 s | 50.9 s / 114 s |
| timeline max / mean | **15.3 KB** / 7.2 KB | 16.4 KB / 8.2 KB |

The equivalence decision generalises (false positives 67 â†’ 52, nothing lost), but the held-out set is clearly worse than the tuning-time eval set (27 false positives on 11 matches): **36 of the 52 are 4-3-3 â†” 4-2-3-1 flip-flops**, 33 of them in two matches (seed 104: 18, seed 105: 15). In seed 104 the away team is a true 4-3-3 throughout and the detector emits 17 candidates in 35 minutes. The two long timelines break the Phase 1 "under ~8 KB" criterion on held-out data.
**Why (best guess):** the same mechanism as 3-5-2 â†” 5-3-2: a 4-3-3's wide forwards drop out of possession (generator `winger_drop_m: 5`), so out-of-possession spells read as 4-2-3-1, and spells longer than 20 s become candidates. Some seeds (personal offsets, possession lengths) sit right on the boundary. The eval seeds 43â€“52 happened to sit mostly on one side of it.
**Screenshot / output:** outputs/failures/2026-10-10_heldout_433_4231_flip.png
**Fix or mitigation:** deliberately **not** fixed now: tuning on the held-out set would contaminate it as well. Options for later (needs a new untouched seed range to measure): classify in- and out-of-possession shapes separately; or require the challenger to hold across both possession phases. Phase 3's agent verification is the intended filter for such candidates. These held-out numbers are the official synthetic numbers.
**Measured impact:** false positives 52 on 10 held-out matches (vs 27 on the tuning-time eval set); 36 / 52 are this pair.

### [2026-10-10] Shape change made while the camera shows only part of the pitch is found minutes late
**Stage:** change detection
**Severity:** degraded

**Input:** synthetic, `eval_synthetic.py` seed 45 (away 4-4-2 â†’ 3-4-3 at 4014 s, inside a broadcast-window stretch 3929â€“4310 s)
**What happened:** the engine reads every window in the stretch as `uncertain` (the team is often entirely off-screen), so the change is only emitted at 4365 s, ~6 min late, and briefly passes through 5-3-2 as the full view returns (two candidates). Strict scoring counts this as a miss plus false positives.
**Why (best guess):** by design: with < 8 of 10 outfield players visible there is no honest formation reading, so the detector waits.
**Screenshot / output:** outputs/failures/2026-10-10_change_hidden_by_low_visibility.png
**Fix or mitigation:** known limitation; `eval_synthetic.py` reports these as "late detections after low visibility". Phase 3's `reanalyse_window` vision tool exists for exactly this case.
**Measured impact:** 4 of 43 true changes missed within 90 s; 3 of those 4 are late detections after low visibility.

### [2026-10-10] Set pieces become candidate shape changes
**Stage:** change detection
**Severity:** wrong output (candidate only)

**Input:** synthetic seed 49, home 4-3-3, corner at ~710â€“738 s
**What happened:** players crowd the box for ~25 s; window labels read 4-2-3-1 for 5 consecutive windows (20 s held) â†’ candidate 4-3-3 â†’ 4-2-3-1, then a second candidate back to 4-3-3.
**Why (best guess):** a 25 s dead-ball situation is longer than the 20 s persistence rule; position data alone cannot tell a set piece from a shape change.
**Screenshot / output:** outputs/failures/2026-10-10_set_piece_false_candidate.png
**Fix or mitigation:** deliberately not tuned away in the detector (raising persistence would delay real alerts). Candidates are verified by the Phase 3 agent (possession `dead`, ball at a corner flag / in the box, re-analysis after the restart).
**Measured impact:** 16 of 27 false-positive candidates across 11 synthetic matches overlap a set piece.

### [2026-10-10] 4-3-3 and 4-2-3-1 are confused
**Stage:** formation
**Severity:** wrong output

**Input:** synthetic, all 11 eval matches
**What happened:** 76 windows of true 4-3-3 were labelled 4-2-3-1; 11 of the 27 false-positive candidates are 4-3-3 â†” 4-2-3-1 pairs.
**Why (best guess):** out of possession a 4-3-3's wide forwards drop (generator: 5 m), so the shape genuinely looks like 4-2-3-1 / 4-5-1. Football analysts argue about the same distinction.
**Screenshot / output:** confusion matrix printed by `py scripts\eval_synthetic.py` (`outputs/eval_synthetic.json`)
**Fix or mitigation:** known limitation; not grouped as one family because single vs double pivot matters to a coach. Possible fix: classify in- and out-of-possession shapes separately.
**Measured impact:** true 4-3-3 read correctly in 97.7 % of confident windows (76 of 3,735 read as 4-2-3-1); 11 of 27 false-positive candidates (41 %).

### [2026-10-10] 3-5-2 and 5-3-2 flip with possession â†’ flood of false candidates
**Stage:** formation / change detection
**Severity:** wrong output

**Input:** synthetic eval matches with a back-three/five team (e.g. seed 43 away, true 5-3-2 from 1110 s)
**What happened:** window labels alternate between 5-3-2 and 3-5-2 with each possession spell; the detector turned every alternation that lasted â‰¥ 20 s into a candidate. First full eval: **89 false positives, 62 of them 3-5-2 â†” 5-3-2**; one match had 32 and a 25 KB timeline.
**Why (best guess):** it is the same system: wing-backs drop into a back five without the ball and push into midfield with it. The dev tuning seeds happened to contain no back-three team, so this only showed up on the eval seeds.
**Screenshot / output:** outputs/failures/2026-10-10_352_532_flip.png
**Fix or mitigation:** config `formations.equivalent: [["3-5-2", "5-3-2"]]`: switching inside a family is not a change; segments vote by family; window labels stay exact so the confusion matrix still shows it. Decision made after seeing eval numbers (football reasoning, not a threshold tweak); dev seeds unchanged by it.
**Measured impact:** false positives 89 â†’ 27; hits 37 â†’ 39 of 43; max timeline 25.2 KB â†’ 8.9 KB (7.9 KB after segments were lengthened to 22.5 min).

### [2026-10-10] Partial (broadcast-style) view gives confident wrong formations
**Stage:** formation
**Severity:** wrong output

**Input:** synthetic match_001, home 4-3-3, broadcast window 1569â€“1812 s (~7 of 10 outfield players visible) with two corners
**What happened:** with `min_players: 6` the template fit labelled the team 4-2-3-1 and 3-4-3 with window confidence up to 0.79 â†’ 4 false candidates in 3 minutes.
**Why (best guess):** when 3+ players are off-screen a whole line can be missing, and a template with one fewer player in that line fits the visible subset just as well. The visibility penalty in the confidence was too mild.
**Screenshot / output:** outputs/failures/2026-10-10_partial_view_min_players_6.png (before) vs outputs/failures/2026-10-10_partial_view_min_players_8.png (after)
**Fix or mitigation:** `tactics.min_players: 8`: a frame is used only when 8+ of 10 outfield players are visible; otherwise the window says `uncertain`. Tuned on dev seeds 1000â€“1002 only.
**Measured impact:** dev seeds: false positives 13 â†’ 5, hits 14/14 unchanged, accuracy when confident 97.8 % â†’ 98.7 %; cost: broadcast-window coverage 52 % â†’ 30 %.

### [2026-10-09] COCO YOLOX misses side-view players on the full 6500 px panorama
**Stage:** detection
**Severity:** wrong output

**Input:** `soccer_side/F_20220220_1_1680_1710.mp4`, frame 0, whole 6500Ã—1000 frame letterboxed to 640Ã—640
**What happened:** 0 persons detected. On a native-resolution 640Ã—640 crop of the same frame: 11 persons (scores 0.65â€“0.85).
**Why (best guess):** letterboxing 6500 px to 640 px shrinks players (median 38 px high) to ~4 px, far below what YOLOX-S can resolve.
**Screenshot / output:** outputs/failures/2026-10-09_yolox_side_fullframe_no_persons.jpg (vs outputs/smoke_opencv_side_crop.jpg)
**Fix or mitigation:** Phase 2: tiled inference at native resolution (~10 tiles per frame over the pitch area).
**Measured impact:** 0 â†’ 11 persons on the same frame (full frame vs one native crop).

### [2026-10-09] COCO YOLOX barely detects top-view (drone) players
**Stage:** detection
**Severity:** wrong output

**Input:** `soccer_top/D_20220220_1_1530_1560.mp4`, frame 0 (3840Ã—2160)
**What happened:** YOLOX-S (OpenCV Model Zoo, COCO) through `cv2.dnn` finds 0 persons on the full frame and on the native 640Ã—640 centre crop (max objectness 0.058 even at a 0.05 threshold), and 1 of 12 GT players on a dense native 1280Ã—640 region (two 640 tiles).
**Why (best guess):** seen from directly above, players are ~30 px blobs (head + shoulders + shadow) with no human silhouette; COCO "person" is learnt from side-on views.
**Screenshot / output:** outputs/failures/2026-10-09_yolox_top_view_near_zero.jpg
**Fix or mitigation:** known limitation of the off-the-shelf model. Phase 2 options to evaluate: fine-tune YOLOX on TeamTrack top-view train boxes (Apache 2.0 + MIT) and export ONNX for `cv2.dnn`; or classical OpenCV detection against the grass (HSV grass mask, background model, `connectedComponentsWithStats`) â€” the top view is a near-orthographic, almost static camera, which suits it.
**Measured impact:** recall â‰ˆ 1/12 on the sampled region.

---

## Failure cases worth looking for

Delete this section before submitting.

- TeamTrack top view: players are tiny from a drone; shadows mistaken for players
- TeamTrack side view: fisheye stretching at the edges; far-side players very small; undistortion cropping players at the borders
- Ground-truth vs detection mismatch: GT boxes may include players the detector never can see (occluded)
- Far-side players too small for the detector
- Two players overlapping â†’ one box, or swapped track IDs
- Goalkeeper or referee shirt colour close to a team colour
- Shadows / floodlights splitting one team into two colour clusters
- Camera pan or zoom breaking the homography
- Hard camera cut mid-clip
- Fewer than ~7 outfield players visible â†’ formation guessed from too little
- Set pieces and goal celebrations producing fake "formations"
- Change detector firing on a short tactical moment (a counter-attack), not a real shape change
- Agent confirming a change it should have rejected (and vice versa)
- Bedrock throttling or timeouts; tool call with malformed arguments

### [2026-10-21] Concurrent status polling briefly blocks atomic status replacement on Windows
**Stage:** local upload/analysis progress polling
**Severity:** recoverable local integration failure

**What happened:** During the connected browser upload flow, a poll reader briefly held `status.json` while the worker attempted to replace it. `Path.replace` raised `PermissionError: [WinError 5] Access is denied`; the worker stopped before completing the upload analysis.

**Fix:** `LocalStorage.write_bytes` retries transient `PermissionError` up to six times with bounded exponential delay while preserving the temporary-file atomic replace. A regression test simulates two transient locks; repeated real status polling and the upload E2E then completed.

### [2026-10-21] Saved advice response looked like a tactical failure after coach context changed
**Stage:** replaying an event with persisted N4 advice
**Severity:** coach-facing confusion

**What happened:** An unfamiliar walkthrough changed the setup context after an advice response had already been saved. The API correctly returned HTTP 409 rather than replace a response associated with another coach side/objective/available-role set, but the card displayed `Tactical advice failed`, which did not explain the saved decision.

**Fix:** When the event already has a coach response, the UI keeps its original suggestion and response visible. If the current setup differs, it explains that the saved response stays linked to its original context and cannot be overwritten. Browser E2E against the persisted-response/context-mismatch case passed. The stranger has been asked to confirm the revised copy; do not count that final confirmation until received.

### [2026-10-23] Agentic calibration comparison exceeded the local evaluation time box
**Stage:** optional OpenCV self-calibration evaluation
**Severity:** measurement incomplete; feature remains disabled

**What happened:** The paired Zenodo test command used more than 11 minutes of aggregate CPU
time. Its first OpenCV pass completed and produced diagnostics, then Nova returned one structured
choice (`static.min_share = 0.75`) in 3.02 s. Its reason cited the static-blob share but incorrectly
called 0.75 a â€œlowerâ€ value although the deterministic setting is 0.6. The process was stopped
during the proposed OpenCV rerun, before measurement or acceptance. The prior six-minute TeamTrack
consistency upload took 777.8 s for perception; a fresh full comparison was not started. A quick
attempt to reuse an old annotation-derived oracle for the auto-calibrated upload produced
implausible P/R/F1 and was excluded because the two saved states do not share the same per-upload
calibration mapping.

**Impact:** The connected structured tool path works, but no Nova-versus-default comparison or
measured loop overhead was obtained. The request used 1,302 input / 95 output tokens, estimated
$0.0006281; session total is 1 real call, under the 20 call / $0.05 cap. Keep
`perception.self_calibration.agentic.enabled` false. Existing deterministic metrics remain context
only; they are not evidence that the new loop helps.

### [2026-10-23] Low-resolution generated-clip duplicate rate was misattributed to TeamTrack

**Stage:** optional Tier 1 perception calibration quick check
**Severity:** degraded player counts and team labelling in the TeamTrack trial; calibration remains off

**What happened:** The previously reported **69% duplicate problem came from a generated clip at
7.4 px/m**, not from TeamTrack. The real TeamTrack 720p copy measured **9.3 px/m** and, with Prompt 1
defaults, had **5.9% duplicates**. Applying the Tier 1 local-scale rule to its first 120 seconds
worsened the measurements: detections/frame **21.8 â†’ 12.8**, White outfield points **8.3 â†’ 2.6**,
and team-labelled share **0.86 â†’ 0.77**. The duplicate share also rose from 5.9% to 9.9%.

**Why:** The generated and TeamTrack clips have different resolution/scale and detector behaviour;
the generated-clip duplicate rate was not transferable evidence for this real footage. Disabling
local-scale on the TeamTrack short window removed many detections and left too few White points.

**Impact / mitigation:** Added a configured lower health bound of **7 outfield points per team** as
well as the existing upper bound, so low player counts cannot be classified healthy. Tier 2 was not
triggered by the Prompt 1 TeamTrack diagnostics because they met the configured ranges. Both tiers
remain OFF, and **Part 2 was not run**; this quick check does not justify enabling either tier.

**Model issue:** The earlier Nova proposal static.min_share = 0.75 described 0.75 as â€œlower than
0.6â€, which is false. Its OpenCV rerun did not complete; the choice was not measured or retained.
