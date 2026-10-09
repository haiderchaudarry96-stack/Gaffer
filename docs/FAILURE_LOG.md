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
