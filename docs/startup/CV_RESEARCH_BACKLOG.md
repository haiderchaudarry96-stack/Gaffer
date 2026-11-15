# Computer vision research backlog

This document tracks known perception limitations and future experiments. It is a research queue only: **Phase 1 does not change models, thresholds, weights, config or CV behavior.** Record a baseline and held-out evaluation before changing any setting.

## Known limitations

| Area | Current evidence / limitation | Proposed research and benchmark |
|---|---|---|
| Player detection | The classical drone detector still admits staff, line clutter, shadows and duplicate detections. A generated 7.4 px/m clip had 69% duplicates; the real TeamTrack 720p derivative at 9.3 px/m had 5.9% with defaults. 720p is weaker on formation agreement. | Score precision/recall/F1 at multiple pitch-coordinate tolerances by scale, lighting, camera and object type; report duplicates, false objects and per-player coverage. Add additional licensed grounds and native resolutions. |
| Player tracking | IDF1 remains modest (about 0.45–0.53 in the documented real eval sets) and per-video self-calibration increased fragmentation on one evaluation. Anonymous IDs can switch. | Measure IDF1, ID switches/player-minute and track fragmentation by occlusion, camera movement and resolution. Compare temporal association methods on identical detections. |
| Pitch calibration | Auto-detection succeeded on documented sets, but a Zenodo corner was 1.4–1.7 m from annotation-implied ground truth; perspective, poor line visibility and lower resolution remain risks. | Collect independent corner labels from several grounds, report corner error and transformed position error by region, and stratify acceptance/refusal behavior by line visibility. |
| Team classification | Kit colour clustering works well on the documented TeamTrack colours, but shadows, similar kits, keepers and officials can distort clusters; unknown labels trade coverage for correctness. | Report per-team precision/recall, unknown share and keeper/official confusion over different kit palettes, sunlight, shade and white balance. Use match-level rather than frame-level splits. |
| Temporal consistency | Short windows, set pieces and a single sparse window can change the estimated formation; White's 16:30 demonstration depends on sparse/free-kick evidence, while Blue's real 18:50 change is missed by the return-leg rule. | Compare shape stability and event latency across annotated sustained changes, stoppages and occlusions; report false alerts and misses without tuning on the test split. Keep the current tactics engine frozen in this phase. |
| Formation estimation | Formation templates share assumptions with synthetic generation; real evaluation is concentrated in one TeamTrack match. Some neighboring shapes are hard to distinguish and fewer visible players lower coverage. | Evaluate per-team and per-formation confusion on independently labelled matches; add confidence calibration and abstention metrics with a held-out club/ground split. |
| Processing performance | The six-minute 4K upload took 28 minutes on the deployed demo server; 720p was about 0.34 s per video second on an idle laptop in one check. Runtime varies with hardware/load. | Profile per-stage latency, memory and cost by resolution, fps, clip duration and hardware; report p50/p95, queue time and measurement environment. Do not infer user-facing ETA from a single run. |
| Ball / possession / pressing | No ball tracking or possession model is present. Current player positions do not justify claims about possession, pressing intensity or in/out-of-possession tactical intent. | First build an annotated ball benchmark with occlusion and size analysis; then define possession/pressing labels and compare their temporal agreement against independent analysts. Until then, keep these claims out of the product UI. |

## Experiment protocol

1. Record the frozen default and exact source/data/licence versions.
2. Split data by match, ground and team before tuning; do not call neighboring minutes independent.
3. State primary metrics, acceptable trade-offs and a stop condition before running experiments.
4. Preserve every miss and failure example with a reviewable artifact and an entry in `docs/FAILURE_LOG.md`.
5. Report runtime hardware, frame sampling, resolution, costs and unavailable inputs alongside quality metrics.
6. Keep the current defaults unless a predeclared held-out result improves the target without a material regression elsewhere.
