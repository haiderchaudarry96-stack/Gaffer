# ruff: noqa: E501  (a table of quoted claims; long lines are the data)
"""Cross-check the numbers quoted in README / TECHNICAL_REPORT / DEVPOST against their source files.

    py scripts/audit_numbers.py            # prints a markdown table; writes outputs/final_audit_numbers.md

Each claim = (where it is used, the text as written, the source file, how to read it, the value as
written, the tolerance). A claim is `ok` when the source gives the stated value (rounded the way
the text rounds it). Claims whose source is a prose record (RECORD.md, DATA_NOTES.md) are listed in
docs/FINAL_AUDIT.md by hand, with the line they come from; this script only covers JSON sources.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load(name: str) -> Any:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def at(obj: Any, path: str) -> Any:
    for part in path.split("/"):
        obj = obj[int(part)] if isinstance(obj, list) else obj[part]
    return obj


# (used in, claim text, source, path, stated value, scale (value*scale rounded to `nd` digits), nd)
CLAIMS: list[tuple[str, str, str, str, float, float, int]] = []


def claim(used: str, text: str, src: str, path: str, stated: float, scale: float = 1.0,
          nd: int = 3) -> None:
    CLAIMS.append((used, text, src, path, stated, scale, nd))


AG = "outputs/eval_agent_final.json"
for arm, key, txt in (("oneshot", "alerted_hits", "one-shot real changes alerted"),
                      ("oneshot", "false_alerts", "one-shot false alerts"),
                      ("rules", "alerted_hits", "rules real changes alerted"),
                      ("rules", "false_alerts", "rules false alerts"),
                      ("llm", "alerted_hits", "agent real changes alerted"),
                      ("llm", "false_alerts", "agent false alerts")):
    val = {"oneshot/alerted_hits": 34, "oneshot/false_alerts": 34, "rules/alerted_hits": 32,
           "rules/false_alerts": 9, "llm/alerted_hits": 32, "llm/false_alerts": 9}[f"{arm}/{key}"]
    claim("README, REPORT §6.3, DEVPOST", txt, AG, f"arms/{arm}/summary/{key}", val, 1, 0)
claim("REPORT §6.3", "true changes", AG, "arms/rules/summary/true_changes", 38, 1, 0)
claim("REPORT §6.3", "candidates", AG, "arms/rules/summary/candidates", 68, 1, 0)
claim("REPORT §6.3", "rules mean alert delay s", AG, "arms/rules/summary/mean_alert_delay_s", 105, 1, 0)
claim("REPORT §6.3", "one-shot mean alert delay s", AG, "arms/oneshot/summary/mean_alert_delay_s", 42, 1, 0)
claim("REPORT §6.3", "rejected real changes (rules)", AG, "arms/rules/summary/rejected_hits", 2, 1, 0)
claim("REPORT §6.3, DEVPOST", "LLM calls", AG, "llm/llm_calls", 195, 1, 0)
claim("REPORT §6.3", "LLM calls per candidate", AG, "llm/llm_calls_per_candidate", 2.9, 1, 1)
claim("REPORT §6.3, DEVPOST", "Bedrock cost per match USD", AG, "llm/mean_cost_per_match", 0.021, 1, 3)
claim("REPORT §6.3", "Bedrock total USD", AG, "llm/cost_usd", 0.21, 1, 2)
claim("REPORT §6.3, DEVPOST", "decisions equal to rules (of 68)", AG, "llm/agreement_with_rules", 68, 1, 0)
claim("REPORT §6.3", "guard blocks", AG, "llm/guard_blocks", 0, 1, 0)

SY = "outputs/eval_synthetic_heldout2.json"
claim("REPORT §8.1", "formation accuracy when confident, %", SY, "all/formation/overall/accuracy_when_confident", 97.7, 100, 1)
claim("REPORT §8.1", "full view when confident, %", SY, "all/formation/full_view/accuracy_when_confident", 97.6, 100, 1)
claim("REPORT §8.1", "broadcast window when confident, %", SY, "all/formation/broadcast/accuracy_when_confident", 98.0, 100, 1)
claim("REPORT §8.1", "strict accuracy, %", SY, "all/formation/overall/accuracy_strict", 77.4, 100, 1)
claim("REPORT §8.1", "true changes", SY, "all/changes/true_changes", 38, 1, 0)
claim("REPORT §8.1", "hits", SY, "all/changes/hits", 34, 1, 0)
claim("REPORT §8.1", "misses", SY, "all/changes/misses", 4, 1, 0)
claim("REPORT §8.1", "false positives", SY, "all/changes/false_positives", 34, 1, 0)
claim("REPORT §8.1", "mean detection delay s", SY, "all/changes/mean_detection_delay_s", 42, 1, 0)
claim("REPORT §8.1", "max detection delay s", SY, "all/changes/max_detection_delay_s", 125, 1, 0)
claim("REPORT §8.1", "new formation right", SY, "all/changes/hits_with_correct_new_formation", 31, 1, 0)
claim("REPORT §8.1", "timeline max KB", SY, "timeline_bytes/max", 14.0, 1 / 1024, 1)
claim("REPORT §8.1", "timeline mean KB", SY, "timeline_bytes/mean", 6.3, 1 / 1024, 1)

TT = "outputs/eval_tracking_top_final.json"
claim("README, REPORT §8.2", "eval F1 at 1 m raw", TT, "results/4/detection/raw/f1", 0.918)
claim("REPORT §8.2", "eval precision", TT, "results/4/detection/raw/precision", 0.872)
claim("REPORT §8.2", "eval recall", TT, "results/4/detection/raw/recall", 0.970)
claim("REPORT §8.2", "eval F1 referees removed", TT, "results/4/detection/referee_removed/f1", 0.984)
claim("REPORT §8.2", "eval team accuracy %", TT, "results/4/teams/accuracy_settled", 98.4, 100, 1)
claim("REPORT §8.2", "eval IDF1", TT, "results/4/identity/idf1", 0.526)
claim("REPORT §8.2", "eval ID switches per player-min", TT, "results/4/identity/id_switches_per_player_minute", 1.80, 1, 2)
T2 = "outputs/eval_second_set_tracking_top_final.json"
claim("README, REPORT §8.2", "eval2 F1 at 1 m raw", T2, "results/4/detection/raw/f1", 0.930)
claim("REPORT §8.2", "eval2 F1 referees removed", T2, "results/4/detection/referee_removed/f1", 0.990)
claim("REPORT §8.2", "eval2 team accuracy %", T2, "results/4/teams/accuracy_settled", 98.8, 100, 1)
claim("REPORT §8.2", "eval2 IDF1", T2, "results/4/identity/idf1", 0.457)
claim("REPORT §8.2", "eval2 ID switches per player-min", T2, "results/4/identity/id_switches_per_player_minute", 1.41, 1, 2)
claim("REPORT §8.2", "eval White formation exact %", "outputs/eval_real_final.json", "top/eval/oracle/home/formation/exact_agreement", 100, 100, 1)
claim("REPORT §8.2", "eval Blue formation exact %", "outputs/eval_real_final.json", "top/eval/oracle/away/formation/exact_agreement", 90.0, 100, 1)
claim("REPORT §8.2", "eval2 White formation exact %", "outputs/eval_second_set_real_final.json", "top/eval2/oracle/home/formation/exact_agreement", 93.5, 100, 1)
claim("REPORT §8.2", "eval2 Blue formation exact %", "outputs/eval_second_set_real_final.json", "top/eval2/oracle/away/formation/exact_agreement", 88.1, 100, 1)
claim("REPORT §8.2", "calibration held-out mean error m (top)", "data/calibration/top.json", "errors/held_out_mean_m", 0.11, 1, 2)
claim("REPORT §8.2", "autodetect correct of 180", "outputs/eval_autodetect.json", "outcomes/success", 180, 1, 0)

ZB, ZF = "outputs/eval_zenodo_before.json", "outputs/eval_zenodo_final.json"
claim("README, REPORT §8.3, DEVPOST", "Zenodo test F1 before", ZB, "test/detection/1m/f1", 0.567)
claim("REPORT §8.3", "Zenodo test precision before", ZB, "test/detection/1m/precision", 0.396)
claim("REPORT §8.3", "Zenodo test recall before", ZB, "test/detection/1m/recall", 0.999)
claim("README, REPORT §8.3, DEVPOST", "Zenodo test F1 after", ZF, "test/detection/1m/f1", 0.855)
claim("REPORT §8.3", "Zenodo test precision after", ZF, "test/detection/1m/precision", 0.765)
claim("REPORT §8.3", "Zenodo test recall after", ZF, "test/detection/1m/recall", 0.970)
claim("REPORT §8.3", "detections per frame before", ZB, "test/per_frame/detections", 63.1, 1, 1)
claim("REPORT §8.3", "detections per frame after", ZF, "test/per_frame/detections", 31.7, 1, 1)
claim("REPORT §8.3", "annotated people per frame", ZF, "test/per_frame/annotated_people", 25.0, 1, 1)
claim("REPORT §8.3", "team accuracy before %", ZB, "test/teams/accuracy", 81, 100, 0)
claim("REPORT §8.3", "team accuracy after %", ZF, "test/teams/accuracy", 98, 100, 0)
claim("REPORT §8.3", "strict coverage home after %", ZF, "test/formation_coverage_strict/home/coverage", 96, 100, 0)
claim("REPORT §8.3", "strict coverage away after %", ZF, "test/formation_coverage_strict/away/coverage", 76, 100, 0)
claim("REPORT §8.3", "strict coverage home before %", ZB, "test/formation_coverage_strict/home/coverage", 0, 100, 0)
claim("REPORT §8.3", "strict coverage away before %", ZB, "test/formation_coverage_strict/away/coverage", 10, 100, 0)
claim("REPORT §8.3", "worst corner error m, final run", ZF, "autodetect_vs_annotations/max_corner_error_m", 1.4, 1, 1)
claim("REPORT §8.3", "worst corner error m, first run", ZB, "autodetect_vs_annotations/max_corner_error_m", 1.74, 1, 2)

R7 = "outputs/teamtrack_720p_check/report.json"
for row, label in (("4k", "4K"), ("720p", "720p")):
    claim("README, REPORT §8.4", f"{label} F1 raw", R7, f"rows/{row}/detection/raw/f1", 0.928)
    claim("REPORT §8.4", f"{label} team accuracy %", R7, f"rows/{row}/teams/accuracy_settled",
          99.0 if row == "4k" else 98.5, 100, 1)
    claim("REPORT §8.4", f"{label} IDF1", R7, f"rows/{row}/identity/idf1", 0.468 if row == "4k" else 0.416)
    claim("REPORT §8.4", f"{label} White formation exact %", R7, f"rows/{row}/formation/home/exact_agreement",
          91.7 if row == "4k" else 74.1, 100, 1)
    claim("REPORT §8.4", f"{label} Blue formation exact %", R7, f"rows/{row}/formation/away/exact_agreement",
          86.2 if row == "4k" else 82.8, 100, 1)
    claim("REPORT §8.4", f"{label} s per video s", R7, f"rows/{row}/seconds_per_video_second",
          1.42 if row == "4k" else 0.34, 1, 2)
claim("REPORT §8.4", "4K referees-removed F1", R7, "rows/4k/detection/referee_removed/f1", 0.978)
claim("REPORT §8.4", "720p referees-removed F1", R7, "rows/720p/detection/referee_removed/f1", 0.958)

ST = "outputs/sample_timing.json"
claim("REPORT §8.6", "TeamTrack sample total s", ST, "samples/0/total_s", 20.6, 1, 1)
claim("REPORT §8.6", "TeamTrack sample pitch check s", ST, "samples/0/pitch_check_s", 1.3, 1, 1)
claim("REPORT §8.6", "TeamTrack sample analysis s", ST, "samples/0/analysis_s", 19.3, 1, 1)
claim("REPORT §8.6", "Zenodo sample total s", ST, "samples/1/total_s", 18.5, 1, 1)
claim("REPORT §8.6", "Zenodo sample pitch check s", ST, "samples/1/pitch_check_s", 1.1, 1, 1)
claim("REPORT §8.6", "Zenodo sample analysis s", ST, "samples/1/analysis_s", 17.3, 1, 1)
claim("REPORT §8.6", "TeamTrack sample px per metre", ST, "samples/0/resolution/px_per_m", 14.0, 1, 1)
claim("REPORT §8.6", "Zenodo sample px per metre", ST, "samples/1/resolution/px_per_m", 14.7, 1, 1)
claim("DEVPOST", "Zenodo s per video s, loaded laptop", ZB, "s_per_video_s", 13.13, 1, 2)
claim("DEVPOST", "Zenodo s per video s, idle laptop", "outputs/eval_zenodo_a4_before.json", "s_per_video_s", 4.39, 1, 2)

GB, GC = "outputs/a4_geo_bench.json", "outputs/a4_geo_bench_c2f.json"
claim("REPORT §4.3", "Zenodo base s per frame", GC, "zenodo/base/s_per_frame", 0.888, 1, 3)
claim("REPORT §4.3", "Zenodo base ORB frames of 24", GC, "zenodo/base/orb_frames", 21, 1, 0)
claim("REPORT §4.3", "Zenodo c2f s per frame", GC, "zenodo/c2f0.5/s_per_frame", 0.097, 1, 3)
claim("REPORT §4.3", "Zenodo c2f ORB frames", GC, "zenodo/c2f0.5/orb_frames", 0, 1, 0)
claim("REPORT §4.3", "Zenodo base line error m", GC, "zenodo/base/line_err_median_m", 0.075, 1, 3)
claim("REPORT §4.3", "Zenodo c2f line error m", GC, "zenodo/c2f0.5/line_err_median_m", 0.079, 1, 3)
claim("REPORT §4.3", "TeamTrack dev base s per frame", GC, "teamtrack_dev/base/s_per_frame", 0.089, 1, 3)
claim("REPORT §4.3", "TeamTrack dev c2f s per frame", GC, "teamtrack_dev/c2f0.5/s_per_frame", 0.089, 1, 3)
claim("REPORT §4.3", "TeamTrack dev line error m", GC, "teamtrack_dev/base/line_err_median_m", 0.087, 1, 3)
claim("REPORT §9", "plain downscale 0.125 s per frame", GB, "zenodo/scale0.125/s_per_frame", 0.035, 1, 3)
claim("REPORT §9", "plain downscale 0.125 line error m", GB, "zenodo/scale0.125/line_err_median_m", 0.121, 1, 3)
for tag, f1, pr, ta, gs, sv in (("a4_before", 0.8553, 0.7648, 98.25, 109.9, 4.39), ("a4_after", 0.8533, 0.7616, 98.1, 18.2, 1.29)):
    z = f"outputs/eval_zenodo_{tag}.json"
    claim("REPORT §4.3", f"Zenodo {tag} F1", z, "test/detection/1m/f1", f1, 1, 4)
    claim("REPORT §4.3", f"Zenodo {tag} precision", z, "test/detection/1m/precision", pr, 1, 4)
    claim("REPORT §4.3", f"Zenodo {tag} team accuracy %", z, "test/teams/accuracy", ta, 100, 2)
    claim("REPORT §4.3", f"Zenodo {tag} geometry s", z, "timing_s/geometry", gs, 1, 1)
    claim("REPORT §4.3", f"Zenodo {tag} s per video s", z, "s_per_video_s", sv, 1, 2)
for tag, ss in (("a4_before", 1.269), ("a4_after", 1.227)):
    claim("REPORT §4.3", f"TeamTrack eval {tag} F1", f"outputs/eval_tracking_top_{tag}.json", "results/4/detection/raw/f1", 0.9185, 1, 4)
    claim("REPORT §4.3", f"TeamTrack eval {tag} s per video s", f"outputs/eval_tracking_top_{tag}.json", "results/4/seconds_per_video_second", ss, 1, 3)
    claim("REPORT §4.3", f"TeamTrack eval {tag} White formation %", f"outputs/eval_real_{tag}.json", "top/eval/oracle/home/formation/exact_agreement", 100, 100, 1)
    claim("REPORT §4.3", f"TeamTrack eval {tag} Blue formation %", f"outputs/eval_real_{tag}.json", "top/eval/oracle/away/formation/exact_agreement", 90.0, 100, 1)

for name, f1, hs, aw in (("shadows", 0.709, 0, 40), ("crop_foreground", None, 33, 51), ("adaptive_gate", None, 8, 73),
                         ("local_scale", None, 92, 79), ("static_objects", None, 91, 79),
                         ("grass_model", None, 96, 76), ("pitch_mask", None, 96, 76)):
    z = f"outputs/eval_zenodo_fno_{name}.json"
    if f1 is not None:
        claim("REPORT §4.2", f"ablation without {name}: F1", z, "test/detection/1m/f1", f1, 1, 3)
    claim("REPORT §4.2", f"ablation without {name}: strict coverage home %", z, "test/formation_coverage_strict/home/coverage", hs, 100, 0)
    claim("REPORT §4.2", f"ablation without {name}: strict coverage away %", z, "test/formation_coverage_strict/away/coverage", aw, 100, 0)
    claim("REPORT §4.2", f"ablation without {name}: crop_exclude_lines recorded off", z, "selfcal/switches/crop_exclude_lines", 0, 1, 0)
for name, hs, aw in (("crop_foreground", 58.2, 38.8), ("adaptive_gate", 4.5, 61.2)):
    z = f"outputs/eval_zenodo_no_{name}.json"
    claim("REPORT §4.2", f"first ablation without {name}: strict home %", z, "test/formation_coverage_strict/home/coverage", hs, 100, 1)
    claim("REPORT §4.2", f"first ablation without {name}: strict away %", z, "test/formation_coverage_strict/away/coverage", aw, 100, 1)
    claim("REPORT §4.2", f"first ablation without {name}: crop_exclude_lines recorded on", z, "selfcal/switches/crop_exclude_lines", 1, 1, 0)
claim("REPORT §4.2", "final strict coverage home %", ZF, "test/formation_coverage_strict/home/coverage", 96, 100, 0)
claim("REPORT §4.2", "final strict coverage away %", ZF, "test/formation_coverage_strict/away/coverage", 76, 100, 0)

CQ = "outputs/eval_synthetic_heldout2_cheq.json"
claim("REPORT §9", "4-3-3 = 4-2-3-1 family: hits 34 -> 28", CQ, "all/changes/hits", 28, 1, 0)
claim("REPORT §9", "4-3-3 = 4-2-3-1 family: false positives 34 -> 16", CQ, "all/changes/false_positives", 16, 1, 0)

# --- 24 Oct morning: demo-window upload re-check with coarse_to_fine ON, eval2 re-run, sample re-encode
U0, U1 = "outputs/upload_check/demo_final_full/upload_check.json", "outputs/upload_check/demo_c2f_full/upload_check.json"
for tag, f, vals in (("23 Oct upload (c2f absent)", U0, (8, 3.06, 559.6, 2738.6, 1388.7)),
                     ("24 Oct upload (c2f ON)", U1, (8, 2.75, 424.1, 2703.1, 1434.5))):
    claim("REPORT §8.5, README", f"{tag}: candidates", f, "summary/candidates", vals[0], 1, 0)
    claim("REPORT §4.3", f"{tag}: s per video s", f, "perception/s_per_video_s", vals[1], 1, 2)
    claim("REPORT §4.3", f"{tag}: geometry s", f, "perception/timing_s/geometry", vals[2], 1, 1)
    claim("REPORT §4.3", f"{tag}: wall s", f, "wall_s", vals[3], 1, 1)
    claim("REPORT §8.5", f"{tag}: OpenCV re-analysis s", f, "summary/opencv_reanalysis_s", vals[4], 1, 1)
claim("REPORT §8.5", "24 Oct upload: confirmed decisions", U1, "summary/decisions/confirmed", 2, 1, 0)
claim("REPORT §8.5", "24 Oct upload: rejected decisions", U1, "summary/decisions/rejected", 1, 1, 0)
claim("REPORT §8.5", "24 Oct upload: uncertain decisions", U1, "summary/decisions/uncertain", 5, 1, 0)
claim("REPORT §8.5", "23 Oct upload: uncertain decisions", U0, "summary/decisions/uncertain", 6, 1, 0)
E2F, E2R = "outputs/eval_second_set_tracking_top_c2f.json", "outputs/eval_second_set_real_c2f.json"
claim("REPORT §4.3", "eval2 c2f F1 raw", E2F, "results/4/detection/raw/f1", 0.93, 1, 3)
claim("REPORT §4.3", "eval2 c2f F1 referees removed", E2F, "results/4/detection/referee_removed/f1", 0.99, 1, 3)
claim("REPORT §4.3", "eval2 c2f team accuracy %", E2F, "results/4/teams/accuracy_settled", 98.8, 100, 1)
claim("REPORT §4.3", "eval2 c2f IDF1", E2F, "results/4/identity/idf1", 0.457, 1, 3)
claim("REPORT §4.3", "eval2 c2f ID switches per player-min", E2F, "results/4/identity/id_switches_per_player_minute", 1.41, 1, 2)
claim("REPORT §4.3", "eval2 c2f White formation exact %", E2R, "top/eval2/oracle/home/formation/exact_agreement", 93.6, 100, 1)
claim("REPORT §4.3", "eval2 c2f Blue formation exact %", E2R, "top/eval2/oracle/away/formation/exact_agreement", 88.1, 100, 1)
claim("REPORT §4.3", "eval2 c2f White coverage %", E2R, "top/eval2/oracle/home/coverage/pipeline", 99.3, 100, 1)
SC = "outputs/sample_clip_reencode.json"
claim("README, REPORT §8.6", "TeamTrack sample new size MB", SC, "rows/crf16/bytes", 32.3, 1e-6, 1)
claim("REPORT §8.6", "TeamTrack sample old size MB", SC, "rows/old/bytes", 218.4, 1e-6, 1)
claim("REPORT §9", "CRF 23 copy size MB (rejected)", SC, "rows/crf23/bytes", 8.6, 1e-6, 1)
claim("REPORT §9", "CRF 12 copy size MB (rejected, too big)", SC, "rows/crf12/bytes", 63.2, 1e-6, 1)
claim("REPORT §8.6", "new sample px per metre", SC, "rows/crf16/px_per_m", 14.0, 1, 1)
claim("REPORT §8.6", "new sample candidates", SC, "rows/crf16/candidates", 0, 1, 0)
claim("REPORT §8.6", "new sample median position difference to the old file m", SC, "rows/crf16/vs_reference/median_position_diff_m", 0.03, 1, 2)
claim("REPORT §8.6", "referee-labelled detections, old file", SC, "rows/old/label_counts/referee", 180, 1, 0)
claim("REPORT §8.6", "referee-labelled detections, new sample", SC, "rows/crf16/label_counts/referee", 124, 1, 0)
claim("REPORT §9", "referee-labelled detections, CRF 23 copy", SC, "rows/crf23/label_counts/referee", 75, 1, 0)


# --- 24 Oct: measured on EC2 after the HTTPS redeploy (public URL, normal upload path)
ET, EU = "outputs/sample_timing_ec2.json", "outputs/ec2_upload_6min_24oct.json"
for i, name in ((0, "TeamTrack"), (1, "Zenodo")):
    tot, pc, an, sv = ((23.5, 3.4, 20.2, 0.55), (23.0, 2.9, 20.1, 0.56))[i]
    claim("REPORT §7.2, §8.6, DEPLOY", f"EC2 {name} sample total s", ET, f"samples/{i}/total_s", tot, 1, 1)
    claim("REPORT §7.2", f"EC2 {name} sample pitch check s", ET, f"samples/{i}/pitch_check_s", pc, 1, 1)
    claim("REPORT §7.2", f"EC2 {name} sample analysis s", ET, f"samples/{i}/analysis_s", an, 1, 1)
    claim("REPORT §7.2", f"EC2 {name} sample s per video s", ET, f"samples/{i}/perception/s_per_video_s", sv, 1, 2)
claim("REPORT §7.2, §10", "EC2 6-min upload server wall s", EU, "progress_detail/elapsed_s", 1679.9, 1, 1)
claim("REPORT §7.2", "EC2 6-min upload detection stage s", EU, "progress_detail/stage_timings_s/detecting", 403.2, 1, 1)
claim("REPORT §7.2", "EC2 6-min upload agent stage s", EU, "progress_detail/stage_timings_s/agent", 1272.2, 1, 1)
claim("REPORT §4.3, §7.2", "EC2 6-min upload s per video s", EU, "perception/s_per_video_s", 1.13, 1, 2)
claim("REPORT §4.3", "EC2 6-min upload geometry s", EU, "perception/timing_s/geometry", 148.1, 1, 1)
claim("REPORT §7.2", "EC2 6-min upload OpenCV re-analysis s", EU, "summary/opencv_reanalysis_s", 1064.9, 1, 1)
claim("REPORT §7.2", "EC2 6-min upload candidates", EU, "summary/candidates", 8, 1, 0)
claim("REPORT §7.2", "EC2 6-min upload confirmed", EU, "summary/decisions/confirmed", 2, 1, 0)
claim("REPORT §7.2", "EC2 6-min upload rejected", EU, "summary/decisions/rejected", 3, 1, 0)
claim("REPORT §7.2", "EC2 6-min upload uncertain", EU, "summary/decisions/uncertain", 3, 1, 0)
claim("REPORT §7.2", "EC2 6-min upload Bedrock calls", EU, "summary/bedrock/calls", 49, 1, 0)
claim("REPORT §7.2", "EC2 6-min upload Bedrock USD", EU, "summary/bedrock/cost_usd", 0.052, 1, 3)
claim("REPORT §7.2", "EC2 6-min upload posture calls", EU, "summary/posture/calls", 2, 1, 0)
claim("REPORT §7.2", "EC2 6-min upload posture USD", EU, "summary/posture/cost_usd", 0.0031, 1, 4)


def main() -> int:
    rows, bad = [], 0
    cache: dict[str, Any] = {}
    for used, text, src, path, stated, scale, nd in CLAIMS:
        try:
            if src not in cache:
                cache[src] = load(src)
            raw = float(at(cache[src], path))
            actual = round(raw * scale, nd)
            ok = abs(actual - round(stated, nd)) < 10 ** (-nd) / 2 + 1e-9
        except Exception as exc:  # missing file or key: reported, never hidden
            actual, ok = f"ERROR {type(exc).__name__}: {exc}", False
        bad += (not ok)
        rows.append(f"| {used} | {text} | {stated:g} | `{src}` `{path}` | {actual} | {'ok' if ok else '**NOT OK**'} |")
    head = ("| used in | claim | stated | source | source says | check |\n|---|---|---|---|---|---|")
    table = head + "\n" + "\n".join(rows)
    (ROOT / "outputs" / "final_audit_numbers.md").write_text(table + "\n", encoding="utf-8")
    print(table)
    print(f"\n{len(CLAIMS)} claims, {bad} not ok", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
