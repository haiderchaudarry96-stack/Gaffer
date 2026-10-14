# Failure log

> **Why this file exists.** The OpenCV competition explicitly asks for "evaluation evidence … including failure cases or limitations", and the technical report must cover limitations and responsible use. Most teams invent these in the last hour and it shows. Log each failure **when it happens**, with a screenshot, while the details are fresh. The best entries become slides in the video.

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
**Measured impact:** e.g. accuracy 78% → 84% after fix
```

---

## Entries

<!-- Add entries here, newest first. -->

### [2026-10-14] Side view: the near assistant referee is output as a 12th "away" player
**Stage:** team colour
**Severity:** wrong output (open)

**Input:** side eval clips 1710–1800 s at 2 fps (`py scripts\eval_tracking.py --view side --whole-source --save`); found by rescoring the saved `outputs/match_state_side_2fps.json`.
**What happened:** the assistant referee on the near touchline (dark navy tracksuit, flag) is detected and tracked as one track for the whole window, and labelled **away in 173 of 180 scored frames**. They stand 0.3–0.8 m outside the touchline, which the contract keeps (5 m off-pitch tolerance, for throw-ins), so the formation engine would see 11 away outfield players. They are all of the unmatched "away" detections that lie > 10 m from any GT player (173 of 251 with the GT margin removed). The dev clip shows a similar rate (1.4 unmatched "away" per frame) and it was not noticed there.
**Why (best guess):** dark navy is close to the away team's dark blue; the classifier down-weights lightness (`teams.l_weight` 0.5), which is where the two differ most. On the drone view the officials' kit falls outside both team gates and they become referees; from the side the near official is large and seen mostly against grass.
**Screenshot / output:** outputs/failures/2026-10-14_side_touchline_person_as_away.jpg
**Fix or mitigation:** open. Candidate: a track that stays outside the touchlines for most of its life is an official or staff member, not a player (players leave the pitch only briefly). Not implemented yet.
**Measured impact:** a phantom away player in 96 % of side eval frames; side detection precision at 2 m 0.794 includes it.

### [2026-10-14] Spare balls behind a goal are tracked as a "home" player
**Stage:** detection / team colour
**Severity:** wrong output (caught by eval, mitigated)

**Input:** drone view, 270 s run at 2 fps (`py scripts\eval_tracking.py --view top --whole-source`), after the keeper fix below.
**What happened:** a small heap of white spare balls ~1 m behind the goal line forms one blob of player size for the classical detector. It is white, like the home shirts, so its track voted "home" and was output as a home outfield player in **198 frames**. It also competed for the goal's keeper slot (see the entry below).
**Why (best guess):** the top-view detector finds non-grass blobs of player size and has no notion of a person; GT has no label for objects, so the blob only shows up as an unmatched "home" detection.
**Screenshot / output:** outputs/failures/2026-10-14_static_spare_balls_home.jpg
**Fix or mitigation:** a track that stays within 0.3 m (95th percentile of its distance from its median position) for 20 s or more is an object, not a person, and is dropped from the output (`perception.static_object`). Thresholds chosen after seeing this case in the eval run. Known risk: a player who stands perfectly still for 20 s+ (e.g. a long stoppage) would be dropped too. Shrinking the search region does not help: it reaches 1 m behind the goal line (`detector.views.top.roi_margin_goal_m`) so that keepers on the line are found, and the balls lie just inside it.
**Measured impact (top eval clips 1560–1800 s, 2 fps):** 0.32 static detections removed per frame; unmatched detections labelled "home" fell from 0.43 to 0.12 per frame (the same amount), so the filter removed objects, not players; raw precision 0.843 → 0.852. The same run's recall fell 0.976 → 0.955 for an unrelated reason: the scorer now counts only what the pipeline outputs, and at 2 fps 0.51 detections per frame never get a track id (0.07 at 4 fps).

### [2026-10-14] Pipeline got the attacking direction backwards, so both keepers got the wrong label
**Stage:** team colour / goalkeepers
**Severity:** wrong output (caught by eval, fixed)

**Input:** drone view, full 270 s run at 2 fps (`py scripts\eval_tracking.py --view top --whole-source`), first version of the keeper logic.
**What happened:** the pipeline inferred "home attacks right"; the oracle (and the keepers' positions) say home attacks left. Consequences: the home keeper (red) was labelled **away goalkeeper in 468 frames**, i.e. every keeper label had the wrong team (`goalkeeper_team_correct` 0.00), and the away keeper (yellow) was labelled **referee in 476 frames**. Settled team accuracy was 0.907 instead of ~0.95.
**Why:** (1) the direction rule (shared with the oracle) compared each team's median distance from its deepest player to each goal line. It relies on the keeper; in the pipeline keepers are only identified *after* the direction is known (their shirts are "other" colours), so it ran on outfield players only, and over this 4.5 min stretch the home attack sat deep in the opponent half. On the 30 s smoke-test window it happened to be right. (2) The keeper slot of a goal went to the "other" track nearest the goal line: spare balls and staff just behind the line beat the yellow keeper.
**Screenshot / output:** outputs/failures/2026-10-14_direction_inverted_keepers.jpg (home keeper boxed as "GK20" in the away colour)
**Fix or mitigation:** (1) direction by a per-frame vote on whose rearmost player is nearer each goal (the offside line keeps attackers behind the last defender, keepers not needed); it gives the same answer as before on both oracle files, and the right answer on the pipeline labels and on the oracle with its keepers removed. (2) A keeper candidate's median position must be on the pitch side of the goal line, and the longest track wins the slot. (3) After (1)+(2) the home keeper was right in every frame, but the away keeper was still "referee": their median position over the run was **20.6 m** from the goal line (they play far off the line), just outside the 20 m keeper zone. The zone was widened to 30 m; referee track medians were ≥ 39 m from both goal lines. This threshold was chosen after seeing eval-clip data.
**Measured impact:** drone view at 2 fps after (1)+(2): settled team accuracy 0.907 → 0.957, keeper team right 0.00 → 1.00; final numbers after (3) in CLAUDE.md.

### [2026-10-14] Tracking at 2 fps: ByteTrack fragments tracks and swaps ids between nearby players
**Stage:** tracking
**Severity:** degraded

**Input:** dev clips only (top D_…_1530, side F_…_1680), `supervision` ByteTrack on the pipeline's detections, ids compared with TeamTrack PlayerIDs at the 2 fps output frames (`scripts/eval_tracking.py`; sweeps on cached detections).
**What happened:** (1) out of the box (boxes enlarged 3×, detector scores passed through) the drone dev clip had **122 ID switches in 30 s for 22 players** (11 per player-minute), IDF1 0.39, 98 tracks: at 2 fps a player moves up to ~4 m (~120 px) between samples, so even 3× boxes stop overlapping. (2) ByteTrack multiplies IoU by the detection score, and the classical detector's "score" is a blob-area ratio, not a confidence: partial blobs never matched. (3) `update_with_detections` maps tracks back to detections by IoU of the Kalman box; with large boxes neighbours overlap, so this step is ambiguous (replaced by centre distance). (4) The remaining switches are swaps between players within 2–4 m of each other (27 of 40 within 2 m on the dev clip): a tackle merges two blobs, and when they part the 0.5 s gap is too long to tell who is who.
**Why (best guess):** IoU association assumes overlap between consecutive frames; 2 fps breaks that for fast, small, look-alike objects.
**Screenshot / output:** outputs/failures/2026-10-14_tracking_swap_2fps.png (a tackle at 1535.5 s reshuffles tracks 5 and 12)
**Fix or mitigation:** matching boxes enlarged by 1 + 12 / fps (7× at 2 fps, 3× at 6 fps), unit scores for association, centre-distance mapping back; tracking at a higher rate than the output (an integer multiple of 2 fps; 5 fps does not land on the 0.5 s output grid, so 4 and 6 fps were measured). The tactics engine never reads track ids: switches only matter through the per-track team vote, so team accuracy decides what is acceptable.
**Measured impact (dev clips):** top: 122 → 41 switches at 2 fps (IDF1 0.39 → 0.71), 24 at 4 fps (0.80), 17 at 6 fps (0.86); side: 42 at 2 fps (IDF1 0.64), 30 at 6 fps (0.71). Eval-clip numbers: see Key numbers in CLAUDE.md.

### [2026-10-14] Side view: a 1 m score mostly measures how the annotator drew the box bottom
**Stage:** detection (evaluation)
**Severity:** degraded (metric), no pipeline output affected

**Input:** TeamTrack side clips, GT boxes vs. the lowest moving-player pixel (temporal-median background of 30 frames per clip, 566 isolated boxes); `py scripts\compare_detectors.py --view side`.
**What happened:** TeamTrack side boxes end **2–3 px below the feet** (median 2 px on the far side, 3 px in the middle and near rows; boxes are also ~3–7 px loose at the top). On the far side one pixel row is 0.4–1 m of pitch depth, so the GT foot point sits ~1 m nearer the camera than the player. A correct detection with a tight box then misses the 1 m criterion. The size of the effect differs between clips: on the dev clip YOLOX boxes ended where GT boxes end (moving GT up 2.5 px made far-half F1 slightly worse, 0.59 → 0.56), on the three eval clips they ended ~2.5 px higher (F1@1 m 0.49 raw → 0.75 with GT moved up 2.5 px; far half 0.32 → 0.63).
**Why (best guess):** hand-drawn boxes with a margin, possibly a different annotator or tool setting per clip; far-side depth resolution of a low panorama camera (see the 10 Oct side-geometry entry).
**Screenshot / output:** outputs/failures/2026-10-14_side_gt_box_margin.png; outputs/compare_detectors_side.json (`+inset` rows)
**Fix or mitigation:** report raw scores (as specified) and, labelled, scores against the GT foot point moved up by the measured margin (`teamtrack.views.side.gt_foot_inset_px: 2.5`, eval only); report the near and far halves separately and add a 2 m column. The oracle still uses the raw box bottom (unchanged since Day 1). Open question for step 5: on the eval clips the YOLOX foot points sit ~2.5 px above the GT ones, i.e. far-side pipeline positions lie up to ~1 m deeper than the oracle's, which will show up as metric error (defensive line, width) unless the oracle also uses the inset.
**Measured impact:** YOLOX F1 at 1 m on the eval clips: 0.49 raw vs 0.75 with the margin removed; at 2 m: 0.78.

### [2026-10-14] Side view: background subtraction loses standing, overlapping and camouflaged players
**Stage:** detection
**Severity:** wrong output (rejected method)

**Input:** side eval clips 1710–1800 s, 150 frames at 2 fps, `cv2.createBackgroundSubtractorMOG2` on the pitch band, blobs filtered by expected person size from the mapper's ground scale; tuned on the dev clip only.
**What happened:** three failure types (2 m criterion, dev clip): (1) players standing still for a while are learnt into the background (15 s history: 102 misses; 60 s history fixed most of it, F1@1 m 0.42 → 0.48); (2) two players at different depths overlap in the image and form one tall blob whose foot point is the nearer player's; (3) a white shirt in front of the white fence/stands, or a lost leg, gives a blob whose foot point is > 2 m off. On the eval clips: F1 at 1 m **0.29** (near half 0.47, far 0.12), at 2 m 0.56, 17.8 unmatched boxes per frame — versus tiled YOLOX 0.49 / 0.78 at 1 m / 2 m.
**Why (best guess):** a static-camera background model sees motion, not people; the side view has 0.47 overlapping player pairs per frame (DATA_NOTES), and far players are 14 × 24 px.
**Screenshot / output:** outputs/failures/2026-10-14_side_background_misses.png; outputs/compare_detectors_side.json
**Fix or mitigation:** tiled YOLOX (cv2.dnn) stays the side-view detector (`detector.views.side.method`); MOG2 stays selectable as a 22× faster fallback (156 ms vs 3.4 s per frame).
**Measured impact:** F1 at 1 m 0.29 (MOG2) vs 0.49 (YOLOX); at 2 m 0.56 vs 0.78.

### [2026-10-10] Top-view classical detector: players on painted lines and touching pairs are missed; referees count as false positives
**Stage:** detection
**Severity:** degraded

**Input:** TeamTrack top view, `py scripts\compare_detectors.py --view top` (8 eval clips, 48 frames; dev clip D_…_1530_1560 used for tuning only).
**What happened:** (1) The first version masked out the projected painted lines; players standing on a line (white shirts are paint-coloured) lost their pixels and disappeared: 6 of the 8 misses in a sample were players on lines. (2) Two players touching (e.g. a tackle) give one blob below the split threshold → one detection between them, matched to neither. (3) The first ROI (3 m beyond the touchlines) picked up the painted "University of Tsukuba / IMAGINE THE FUTURE" text, corner flags and goal frames: 43 extra blobs per frame on the dev clip. (4) The remaining ~4 unmatched detections per frame are real people GT does not label: on the pitch it is the referee in every inspected case, outside the lines the assistant referee and staff (3.0 of the 4.0 per frame are outside the lines).
**Why (best guess):** colour cannot separate a white shirt from white paint; area alone cannot separate two touching players from one large one; GT contains only the 22 players.
**Screenshot / output:** outputs/failures/2026-10-10_top_classical_misses.jpg (misses before the line fix), outputs/failures/2026-10-10_top_classical_extras_on_pitch.jpg (all the referee)
**Fix or mitigation:** (1) "lines are thin, players are wide": inside the projected line band only foreground that survives a 0.4 m morphological opening is kept, and blobs lying ≥ 97 % inside the band (crossing remnants) are dropped; (3) geometric exclusions from the homography: 1 m margin beyond the lines, corner-flag squares, goal-frame strips. (2) open; (4) the team classifier (Day 2) puts referees in their own cluster, and eval reports them separately.
**Measured impact:** dev clip precision 0.33 → 0.84 (ROI exclusions); eval recall 0.966 → 0.978 (line opening), precision 0.843, F1 0.906, isolated-player recall 0.991.

### [2026-10-10] Off-the-shelf YOLOX stays useless on the drone view even tiled at native resolution
**Stage:** detection
**Severity:** wrong output (rejected method)

**Input:** same 8 eval clips; YOLOX-S (COCO) in `cv2.dnn` on overlapping 640 px tiles over the pitch, cross-tile NMS; 12 frames.
**What happened:** recall at 1 m: **0.06** (confidence 0.3), 0.14 (confidence 0.1), **0.54** with tiles upscaled 2× — at 5.0 s, 5.1 s and 18.1 s per 4K frame on the laptop CPU. The classical OpenCV detector reaches 0.978 recall at 0.08 s per frame.
**Why (best guess):** seen from directly above a player is a ~30 px blob without a human silhouette (Phase 0 entry); upscaling helps a little but the shape is still not a COCO "person".
**Screenshot / output:** outputs/failures/2026-10-10_top_yolox_vs_classical.jpg; numbers in outputs/compare_detectors_top.json
**Fix or mitigation:** classical detector chosen for the top view (config `detector.views.top.method`). Fine-tuning YOLOX was not needed. YOLOX stays the side-view detector, where players look like people.
**Measured impact:** F1@1 m 0.11 / 0.24 / 0.65 (YOLOX variants) vs 0.906 (classical), 60–220× slower.

### [2026-10-10] The drone wobbles within a clip: one homography per clip is not enough
**Stage:** homography
**Severity:** degraded

**Input:** all 9 top clips, frames at 0 / 10 / 20 / 29.5 s, `py scripts\eval_drift.py`.
**What happened:** the image moves up to ~14 px relative to the calibration frame, and not only between clips: within one clip it shifts by up to ~10 px back and forth. Anchoring once per clip (at its first frame) is sometimes *worse* than no correction at all (e.g. 1690 s: 0.37 m anchored per clip vs 0.22 m uncorrected), because the drone swings back past the reference.
**Why (best guess):** a hovering drone, not a locked camera; wind.
**Screenshot / output:** outputs/failures/2026-10-10_drone_drift.png; outputs/eval_drift_top.json
**Fix or mitigation:** re-anchor **every sampled frame** (`perception/drift.py`: line image → `cv2.phaseCorrelate` → `cv2.findTransformECC` affine, ORB + `estimateAffinePartial2D` fallback), ~125 ms per frame. Caveat: the line-alignment error is measured on the same painted lines the alignment uses, so it shows consistency with the lines, not independent ground truth.
**Measured impact:** median pitch-line alignment error over 36 sampled frames: **0.198 m** uncorrected → 0.089 m anchored per clip (p90 0.268 m) → **0.040 m** anchored every frame (p90 0.047 m, = the calibration frame's own 0.041 m); max shift 13.8 px; 142 ms per frame.

### [2026-10-10] Top and side TeamTrack clips with the same time in their names are not simultaneous
**Stage:** homography (cross-view check) / data
**Severity:** wrong assumption (no output affected yet)

**Input:** `D_20220220_1_1680_1710` (drone) vs `F_20220220_1_1680_1710` (side), GT boxes mapped to pitch metres with both Phase 2 calibrations.
**What happened:** at nominal t = 1680 s the drone's 22 players are all in the right half while the side camera's are attacking the left goal; team centroids differ by ~35 m. A search over every time offset from −270 to +120 s, four orientation hypotheses (drone rotated 180°, not rotated, mirrored in x, mirrored in y) and three team mappings (same, swapped, ignored) never brings the two views closer than **14 m** mean matched-player distance; a genuine match should be ~2 m (the drone against itself 0.5 s later: 1.8 m).
**Why (best guess):** the file names carry each camera's own clip time, not a shared match clock (or the files come from different parts of the recording). DATA_NOTES inferred the overlap from file names only.
**Screenshot / output:** outputs/failures/2026-10-10_views_not_simultaneous.png
**Fix or mitigation:** DATA_NOTES corrected; the cross-view consistency check is dropped (there is no simultaneous pair in our files). Both views are evaluated independently against their own GT. The drone's 180° orientation therefore rests on within-view evidence only (keeper sides, assistant referee on the near touchline, upside-down text); it is a convention inside the top view's MatchState and does not affect any metric.
**Measured impact:** cross-view comparison not possible with the downloaded files.

### [2026-10-10] Side panorama: stitching ghost at the edges, far-side geometry only good to ~1–2 m
**Stage:** homography
**Severity:** degraded

**Input:** `F_20220220_1_1680_1710.mp4` frame 0, side calibration.
**What happened:** (1) at the near-right corner the goal line appears **twice**, ~12 px apart, with green/magenta fringes: a stitching seam (the left edge is similarly smeared). (2) On the far side, lines are 1–2 px thin and meet at grazing angles, and one image row spans 0.5–1 m of depth: automatic snapping slid landmarks 8–115 px along the lines, so on the side view 18 of 29 landmarks keep their hand-picked positions (snaps capped at 6 px). Held-out error is worst on far landmarks (`half_far` 1.77 m, `pa_L_goal_far` ~1.0 m) vs 0.2–0.5 m near the camera. The near ends of both penalty arcs cannot be located at all (arc and box line merge) and are excluded.
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
**Why (best guess):** the panorama behaves like one very wide **rectilinear** image looking straight across the pitch: every line parallel to the touchlines is a horizontal image row (near touchline at 882–895 px over the full 6500 px), goal lines converge to the centre, the halfway line is vertical. That is pinhole geometry, which a homography represents exactly; the remaining errors come from stitching seams, which sections absorb.
**Screenshot / output:** outputs/failures/2026-10-10_side_panorama_model_comparison.jpg (bird's-eye rectifications); all images in outputs/calibration/ (`side_original.jpg`, `side_overlay_<model>.jpg`, `side_birdseye_<model>.jpg`, `side_fisheye_undistorted.jpg`)
**Fix or mitigation:** use sectioned homographies (chosen automatically by held-out error); `cv2.fisheye` stays in `undistort.py` as a measured baseline.
**Measured impact:** held-out landmark error 0.86 m (fisheye) → 0.53 m (sectioned).

### [2026-10-10] Held-out check: 4-3-3 ↔ 4-2-3-1 flip-flops double the false positives; timeline exceeds 8 KB
**Stage:** formation / change detection (honesty check on Phase 1)
**Severity:** wrong output (candidates only)

**Input:** 10 fresh synthetic matches, seeds 100–109 (never used for tuning or eval before), run with the Phase 1 engine **unchanged**, once with and once without `formations.equivalent: [["3-5-2", "5-3-2"]]`. Run via a temporary config copy (`eval.synthetic.dev_seeds = 100..109`, `--dev`), outputs `outputs/eval_synthetic_heldout.json` and `outputs/eval_synthetic_heldout_noeq.json`.
**What happened:**

| held-out seeds 100–109 | with equivalence | without |
|---|---|---|
| formation accuracy when confident (exact) | 97.0 % | 97.0 % |
| coverage (confident windows) | 79.3 % | 79.1 % |
| strict accuracy (uncertain = wrong) | 76.9 % | 76.8 % |
| shape changes: hits / true | 31 / 36 | 31 / 36 |
| misses (found late after low visibility) | 5 (4) | 5 (4) |
| **false positives** | **52** | 67 |
| mean / max detection delay | 51.4 s / 105 s | 50.9 s / 114 s |
| timeline max / mean | **15.3 KB** / 7.2 KB | 16.4 KB / 8.2 KB |

The equivalence decision generalises (false positives 67 → 52, nothing lost), but the held-out set is clearly worse than the tuning-time eval set (27 false positives on 11 matches): **36 of the 52 are 4-3-3 ↔ 4-2-3-1 flip-flops**, 33 of them in two matches (seed 104: 18, seed 105: 15). In seed 104 the away team is a true 4-3-3 throughout and the detector emits 17 candidates in 35 minutes. The two long timelines break the Phase 1 "under ~8 KB" criterion on held-out data.
**Why (best guess):** the same mechanism as 3-5-2 ↔ 5-3-2: a 4-3-3's wide forwards drop out of possession (generator `winger_drop_m: 5`), so out-of-possession spells read as 4-2-3-1, and spells longer than 20 s become candidates. Some seeds (personal offsets, possession lengths) sit right on the boundary. The eval seeds 43–52 happened to sit mostly on one side of it.
**Screenshot / output:** outputs/failures/2026-10-10_heldout_433_4231_flip.png
**Fix or mitigation:** deliberately **not** fixed now: tuning on the held-out set would contaminate it as well. Options for later (needs a new untouched seed range to measure): classify in- and out-of-possession shapes separately; or require the challenger to hold across both possession phases. Phase 3's agent verification is the intended filter for such candidates. These held-out numbers are the official synthetic numbers.
**Measured impact:** false positives 52 on 10 held-out matches (vs 27 on the tuning-time eval set); 36 / 52 are this pair.

### [2026-10-10] Shape change made while the camera shows only part of the pitch is found minutes late
**Stage:** change detection
**Severity:** degraded

**Input:** synthetic, `eval_synthetic.py` seed 45 (away 4-4-2 → 3-4-3 at 4014 s, inside a broadcast-window stretch 3929–4310 s)
**What happened:** the engine reads every window in the stretch as `uncertain` (the team is often entirely off-screen), so the change is only emitted at 4365 s, ~6 min late, and briefly passes through 5-3-2 as the full view returns (two candidates). Strict scoring counts this as a miss plus false positives.
**Why (best guess):** by design: with < 8 of 10 outfield players visible there is no honest formation reading, so the detector waits.
**Screenshot / output:** outputs/failures/2026-10-10_change_hidden_by_low_visibility.png
**Fix or mitigation:** known limitation; `eval_synthetic.py` reports these as "late detections after low visibility". Phase 3's `reanalyse_window` vision tool exists for exactly this case.
**Measured impact:** 4 of 43 true changes missed within 90 s; 3 of those 4 are late detections after low visibility.

### [2026-10-10] Set pieces become candidate shape changes
**Stage:** change detection
**Severity:** wrong output (candidate only)

**Input:** synthetic seed 49, home 4-3-3, corner at ~710–738 s
**What happened:** players crowd the box for ~25 s; window labels read 4-2-3-1 for 5 consecutive windows (20 s held) → candidate 4-3-3 → 4-2-3-1, then a second candidate back to 4-3-3.
**Why (best guess):** a 25 s dead-ball situation is longer than the 20 s persistence rule; position data alone cannot tell a set piece from a shape change.
**Screenshot / output:** outputs/failures/2026-10-10_set_piece_false_candidate.png
**Fix or mitigation:** deliberately not tuned away in the detector (raising persistence would delay real alerts). Candidates are verified by the Phase 3 agent (possession `dead`, ball at a corner flag / in the box, re-analysis after the restart).
**Measured impact:** 16 of 27 false-positive candidates across 11 synthetic matches overlap a set piece.

### [2026-10-10] 4-3-3 and 4-2-3-1 are confused
**Stage:** formation
**Severity:** wrong output

**Input:** synthetic, all 11 eval matches
**What happened:** 76 windows of true 4-3-3 were labelled 4-2-3-1; 11 of the 27 false-positive candidates are 4-3-3 ↔ 4-2-3-1 pairs.
**Why (best guess):** out of possession a 4-3-3's wide forwards drop (generator: 5 m), so the shape genuinely looks like 4-2-3-1 / 4-5-1. Football analysts argue about the same distinction.
**Screenshot / output:** confusion matrix printed by `py scripts\eval_synthetic.py` (`outputs/eval_synthetic.json`)
**Fix or mitigation:** known limitation; not grouped as one family because single vs double pivot matters to a coach. Possible fix: classify in- and out-of-possession shapes separately.
**Measured impact:** true 4-3-3 read correctly in 97.7 % of confident windows (76 of 3,735 read as 4-2-3-1); 11 of 27 false-positive candidates (41 %).

### [2026-10-10] 3-5-2 and 5-3-2 flip with possession → flood of false candidates
**Stage:** formation / change detection
**Severity:** wrong output

**Input:** synthetic eval matches with a back-three/five team (e.g. seed 43 away, true 5-3-2 from 1110 s)
**What happened:** window labels alternate between 5-3-2 and 3-5-2 with each possession spell; the detector turned every alternation that lasted ≥ 20 s into a candidate. First full eval: **89 false positives, 62 of them 3-5-2 ↔ 5-3-2**; one match had 32 and a 25 KB timeline.
**Why (best guess):** it is the same system: wing-backs drop into a back five without the ball and push into midfield with it. The dev tuning seeds happened to contain no back-three team, so this only showed up on the eval seeds.
**Screenshot / output:** outputs/failures/2026-10-10_352_532_flip.png
**Fix or mitigation:** config `formations.equivalent: [["3-5-2", "5-3-2"]]`: switching inside a family is not a change; segments vote by family; window labels stay exact so the confusion matrix still shows it. Decision made after seeing eval numbers (football reasoning, not a threshold tweak); dev seeds unchanged by it.
**Measured impact:** false positives 89 → 27; hits 37 → 39 of 43; max timeline 25.2 KB → 8.9 KB (7.9 KB after segments were lengthened to 22.5 min).

### [2026-10-10] Partial (broadcast-style) view gives confident wrong formations
**Stage:** formation
**Severity:** wrong output

**Input:** synthetic match_001, home 4-3-3, broadcast window 1569–1812 s (~7 of 10 outfield players visible) with two corners
**What happened:** with `min_players: 6` the template fit labelled the team 4-2-3-1 and 3-4-3 with window confidence up to 0.79 → 4 false candidates in 3 minutes.
**Why (best guess):** when 3+ players are off-screen a whole line can be missing, and a template with one fewer player in that line fits the visible subset just as well. The visibility penalty in the confidence was too mild.
**Screenshot / output:** outputs/failures/2026-10-10_partial_view_min_players_6.png (before) vs outputs/failures/2026-10-10_partial_view_min_players_8.png (after)
**Fix or mitigation:** `tactics.min_players: 8`: a frame is used only when 8+ of 10 outfield players are visible; otherwise the window says `uncertain`. Tuned on dev seeds 1000–1002 only.
**Measured impact:** dev seeds: false positives 13 → 5, hits 14/14 unchanged, accuracy when confident 97.8 % → 98.7 %; cost: broadcast-window coverage 52 % → 30 %.

### [2026-10-09] COCO YOLOX misses side-view players on the full 6500 px panorama
**Stage:** detection
**Severity:** wrong output

**Input:** `soccer_side/F_20220220_1_1680_1710.mp4`, frame 0, whole 6500×1000 frame letterboxed to 640×640
**What happened:** 0 persons detected. On a native-resolution 640×640 crop of the same frame: 11 persons (scores 0.65–0.85).
**Why (best guess):** letterboxing 6500 px to 640 px shrinks players (median 38 px high) to ~4 px, far below what YOLOX-S can resolve.
**Screenshot / output:** outputs/failures/2026-10-09_yolox_side_fullframe_no_persons.jpg (vs outputs/smoke_opencv_side_crop.jpg)
**Fix or mitigation:** Phase 2: tiled inference at native resolution (~10 tiles per frame over the pitch area).
**Measured impact:** 0 → 11 persons on the same frame (full frame vs one native crop).

### [2026-10-09] COCO YOLOX barely detects top-view (drone) players
**Stage:** detection
**Severity:** wrong output

**Input:** `soccer_top/D_20220220_1_1530_1560.mp4`, frame 0 (3840×2160)
**What happened:** YOLOX-S (OpenCV Model Zoo, COCO) through `cv2.dnn` finds 0 persons on the full frame and on the native 640×640 centre crop (max objectness 0.058 even at a 0.05 threshold), and 1 of 12 GT players on a dense native 1280×640 region (two 640 tiles).
**Why (best guess):** seen from directly above, players are ~30 px blobs (head + shoulders + shadow) with no human silhouette; COCO "person" is learnt from side-on views.
**Screenshot / output:** outputs/failures/2026-10-09_yolox_top_view_near_zero.jpg
**Fix or mitigation:** known limitation of the off-the-shelf model. Phase 2 options to evaluate: fine-tune YOLOX on TeamTrack top-view train boxes (Apache 2.0 + MIT) and export ONNX for `cv2.dnn`; or classical OpenCV detection against the grass (HSV grass mask, background model, `connectedComponentsWithStats`) — the top view is a near-orthographic, almost static camera, which suits it.
**Measured impact:** recall ≈ 1/12 on the sampled region.

---

## Failure cases worth looking for

Delete this section before submitting.

- TeamTrack top view: players are tiny from a drone; shadows mistaken for players
- TeamTrack side view: fisheye stretching at the edges; far-side players very small; undistortion cropping players at the borders
- Ground-truth vs detection mismatch: GT boxes may include players the detector never can see (occluded)
- Far-side players too small for the detector
- Two players overlapping → one box, or swapped track IDs
- Goalkeeper or referee shirt colour close to a team colour
- Shadows / floodlights splitting one team into two colour clusters
- Camera pan or zoom breaking the homography
- Hard camera cut mid-clip
- Fewer than ~7 outfield players visible → formation guessed from too little
- Set pieces and goal celebrations producing fake "formations"
- Change detector firing on a short tactical moment (a counter-attack), not a real shape change
- Agent confirming a change it should have rejected (and vice versa)
- Bedrock throttling or timeouts; tool call with malformed arguments
