# Agent trace examples (real footage)

Three cases from the agent runs on real TeamTrack drone footage (rules frozen, config fingerprint `ca4ff9bbf7b01c6c`), copied from the recorded traces. `R0` is the candidate card (the first pass over the stored positions); `R1, R2, …` are tool results, the handles that decisions and alerts cite. The **next** column is what the result made the agent do. Times are match clock (mm:ss). All cases come from one match, so they are traces, not accuracy numbers (those are on synthetic seeds 110–119, AGENT_DESIGN §14).

## (a) White 4-4-2 → 3-4-3 at 16:30: low coverage → OpenCV second look at 6 fps → confirmed → evidence → pending alert

Demonstration window 15:00–21:00 (chosen with the ground-truth positions because the half's two lasting changes happen in it). Agent = Nova 2 Lite on Bedrock, `outputs/agent_video_taskE/trace_llm.jsonl`; the rules arm (`trace_rules.jsonl`) made the same calls.

| ref | actor | call | key result | next |
|---|---|---|---|---|
| R0 | code | candidate card | first pass: only 52 % of the frames in the 45 s before the change show at least 8 of White's outfield players (60 % needed) → rules `need_more`, missing: camera check, second look | check the camera |
| R1 | Nova | `check_frame_quality` 15:45–18:05 | OpenCV, 11.3 s: pitch lines fit 100 % of sampled frames, camera shift 0.4 px/s, zoom 0.2 %, no cut → camera usable; still `need_more` (coverage) | second look, highest rate |
| R2 | Nova | `reanalyse_window` 15:45–18:05 at 6 fps | OpenCV perception re-run on 840 frames (252 s on the laptop CPU in the rules run; cache hit here): **3-4-3 in 91 % of 11 clear readings** over the 60 s after detection, no return to 4-4-2 → rules `confirm` | record it |
| R3 | Nova | `record_decision(confirmed)`, cites R1, R2 | recorded reason (code): "new shape held in 91% of 11 confident windows over 60 s, no revert" | render the evidence |
| R4 | Nova | `render_evidence` | OpenCV: the 16:45 frame with every player and White's 3-4-3 lines projected through that frame's homography, plus before/after shape panels | create the alert |
| R5 | Nova | `propose_alert` | `alr_teamtrack_top_w900_1260_evt_003`, status **pending**: it waits for the coach to approve or reject | — |

5 Nova calls, 15.7 k input / 0.4 k output tokens, $0.0058. **Honest reading:** the first pass alone would also have confirmed (85 % of 13 readings). The OpenCV results decided the path (a second look at 6 fps instead of 4 fps because coverage was low) and produced the evidence; they did not change the decision. Build step 7 replaced the coach-facing text and the picture, not the decision (replayed and asserted). The alert's explanation is now "White played 3-4-3 from 16:30 because it stayed there in 91% of 11 clear readings over the next 60 seconds [R2]"; the step-6 text said "held for over 20 seconds". The "before" panel now shows a typical 4-4-2 (15:05–15:35) instead of a set piece: `outputs/agent_video_step7/evidence/teamtrack_top_w900_1260/evt_003.jpg`.

## (b) Blue 3-5-2 → 4-4-2 at 26:35: the second look contradicts the first-pass revert, the decision stays

Drone eval set 25:30–30:00, rules arm, `outputs/agent_video_final/trace_rules.jsonl` (Nova's run looked at 6 fps and got the same 17 % of 12).

| ref | actor | call | key result | next |
|---|---|---|---|---|
| R0 | code | candidate card | first pass: Blue back in 3-5-2 at 28:05, 55 s after detection ("reverted") → would reject, but on video no verdict without a second look (`need_more`) | check the camera |
| R1 | rules | `check_frame_quality` 25:50–28:10 | OpenCV, 8.0 s: lines fit 100 %, shift 2.4 px/s, no cut | second look |
| R2 | rules | `reanalyse_window` 25:50–28:10 at 4 fps | OpenCV re-run, 560 frames (166 s): **no return to 3-5-2 found**, because the 4-4-2 appears in only 17 % of 12 clear readings → rules `reject` (persistence) | record it |
| R3 | rules | `record_decision(rejected)` | "new shape held in only 17% of 12 confident windows after detection" | done |

The second look contradicts the first pass's claim (no revert); the decision stays (rejected) and the reason changes. On real footage no second look changed a decision (0 of 14 candidates).

## (c) Simulated pan/zoom on real frames: OpenCV refuses, no second look, no alert

The 21:40–24:00 window of the drone clip (eval2 evt_001, Blue 3-4-3 → 4-4-2), re-encoded as a sliding, zooming crop of the real 4K frames (150 px/s, ±12 % zoom), standing in for a broadcast-style camera (no real pan/zoom clip is held). `outputs/agent_video/report.json` (`simulated_pan`), `outputs/agent_video/trace_simpan.jsonl` (second run; the first used a jumpy simulation, FAILURE_LOG 15 Oct).

| ref | actor | call | key result | next |
|---|---|---|---|---|
| R0 | code | candidate card | first pass: 4-4-2 in only 27 % of 11 readings → would reject | check the camera |
| R1 | rules | `check_frame_quality` 21:40–24:00 | OpenCV, 17.8 s: pitch lines fit only 33 % of frames, camera moves 190 px/s, zoom changes 30 % → rules `refuse` | no second look: positions from a moving camera are not valid |
| R2 | rules | `record_decision(uncertain)` | "camera geometry not valid: homography ok in 33% of frames, camera moves 190 px/s, zoom changes 30%" | done, no alert |

The only real-frame case where the OpenCV result changes both the next call (the re-analysis is skipped) and the decision (uncertain where the first pass alone says reject). The camera motion is synthetic.

**Missed change:** Blue 4-4-2 → 4-2-3-1 at 18:50 (demo window evt_007) is rejected by the return-leg rule (it reverses Blue's 18:00 switch), although the 6 fps second look saw 4-2-3-1 in 100 % of 12 readings and the ground truth shows it held 220 s; the tested fix added 25 false alerts on synthetic data and is off (FAILURE_LOG 2026-10-17).

## Reproduce

```powershell
py scripts\run_agent_video.py --out outputs\agent_video_taskE --sets w900 --candidates evt_003,evt_007 [--arm llm]   # (a), needs the 900-1260 s MatchState
py scripts\run_agent_video.py --out outputs\agent_video_final --sets eval2,eval,side_eval2 [--arm llm]               # (b)
py scripts\run_agent_video.py --sets "" --simulated-pan                                                               # (c)
py scripts\explain_real.py ; py scripts\explain_real.py --render    # step 7: explanations + re-rendered evidence, decisions replayed and asserted
```
