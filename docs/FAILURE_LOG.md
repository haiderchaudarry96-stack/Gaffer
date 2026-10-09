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
