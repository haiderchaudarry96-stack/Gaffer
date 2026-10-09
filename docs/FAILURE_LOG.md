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
