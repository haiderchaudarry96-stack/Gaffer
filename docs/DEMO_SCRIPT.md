# Gaffer demo video: script, shot list and recording checklist

Written for: the author, to record in his own voice. Target length **4:45** (hard limit 5:00 for Devpost). About 650 spoken words at an easy 140 words a minute. No music, no copyrighted material, no faces: the footage is TeamTrack (MIT, top-down drone, players are dots), the second clip is Zenodo (CC BY 4.0, top-down).

**Before you record:** run the app locally with Bedrock off (`py scripts\serve_no_bedrock.py --port 8000 --out outputs\api_no_bedrock`) or use the live site. The replay and the 16:30 alert are the same either way. Use the live site (https://gaffer-tactics.duckdns.org/, fallback http://13.210.196.109/) if you want the chat answer to come from Bedrock.

Name and school are taken from the README footer ("Haider Sultan, FAST-NUCES, Pakistan"). Change them in section 1 if that is not how you want to say them.

## Script

Each section has: the time window, what is on screen, and what to say. Say it in your own words; keep the numbers exact.

### 1. Team (0:00–0:20)

**On screen:** the landing page hero, then your name card (plain text "Haider Sultan · FAST-NUCES, Pakistan · solo project").

**Say:** "Hi, I'm Haider Sultan, a student at FAST-NUCES in Pakistan. This is Gaffer, my entry for the OpenCV AI Competition. I built it on my own, with AI coding assistants helping to write the code; I designed it, directed it, tested it and reviewed it."

### 2. The problem (0:20–0:45)

**On screen:** the landing page, slowly scrolling past the headline and the "what it does" steps.

**Say:** "Professional clubs pay analysts to tell them when the other team changes shape. A grassroots coach has a phone, maybe a drone, and no analyst. Gaffer watches the match video with OpenCV 5, works out each team's formation, spots the moment a team switches shape, and before it speaks, it checks its own eyes."

### 3. Start the recorded match (0:45–1:30)

**On screen:** open the app (`/app`), then choose *Live analysis*, confirm the setup dialog. The video plays beside the 2D pitch from 15:00. Set the speed to 4×.

**Say:** "This is real footage: an amateur match filmed from a drone, from the TeamTrack dataset. This is a recorded replay, not a live camera. On the left the video, on the right OpenCV's own view of it: every dot is a detected player, coloured by team, placed on the pitch with a homography. The strip above the timeline shows the shape each team is playing."

### 4. The 16:30 change appears (1:30–2:05)

**On screen:** the clock reaches 16:30. The candidate appears as "checking". The timeline shows White's shape switching from 4-4-2 to 3-4-3. Pause on it.

**Say:** "At sixteen thirty, White moves from four-four-two to three-four-three. The tactics engine only raises a candidate. It does not trust itself yet, and neither should you: formations read from video are noisy. A free kick, a wobbling drone, a shadow, any of them can fake a change."

### 5. The agent checks it: the Agentic Vision moment (2:05–2:50)

**On screen:** open the candidate's *How I checked this* trace. Show, one after another: the first-pass card ("only 52 % of frames show enough White players"), `check_frame_quality`, then `reanalyse_window` at 6 fps, then the 91 % result.

**Say:** "Here is the agent, running on Amazon Bedrock. Its first pass found only fifty-two percent of the frames had enough White players. So it did not decide. It called a tool: check frame quality, where OpenCV measures whether the camera is still and the pitch lines are fitted. The camera is fine. Then, because coverage was low, it asked OpenCV for a second look at six frames per second instead of four. **That OpenCV result changed the agent's next tool call.** The second look found three-four-three in ninety-one percent of eleven clear readings. Only then does it confirm."

### 6. Evidence and the coach's decision (2:50–3:20)

**On screen:** the alert card at 18:05: the evidence image (frame with formation lines plus before/after shapes), the plain-words reason, the Approve / Reject buttons. Click Approve.

**Say:** "The alert comes with proof: the frame, the formation lines, and the shape before and after. Nothing happens without the coach: the alert is pending until I approve or reject it. And if the footage does not support a change, the agent says uncertain and shows why, instead of guessing."

### 7. The chat (3:20–3:40)

**On screen:** open the chat **on the live site** (Bedrock is on there; a local server with Bedrock off only shows an "unavailable" message); type "When did White change shape, and was the change confirmed?" and show the grounded answer with its citation.

**Say:** "I can ask the analyst questions. Its answers come from the stored results and cite them. If I ask something the data does not support, it says so."

### 8. A ground it has never seen (3:40–4:10)

**On screen:** upload step: click the "New ground (Zenodo)" sample, show the credit line (Synowiec, Nowak, Kamola, CC BY 4.0) and the Upload button; the pitch confirmation ("Is this your pitch?"), then the result: dots on the 2D pitch.

**Say:** "A demo on one match proves little, so I tested on a different ground: a drone clip from another pitch, artificial turf, low sun, shadows as long as the players. Before I added per-video self-calibration, OpenCV found sixty-three people per frame for twenty-five real ones. After, it finds thirty-two, and the F1 score goes from point five seven to point eight six. It's thirty seconds, too short for a shape change, but it shows players and teams on a pitch Gaffer was never tuned on."

### 9. The refused pan (4:10–4:25)

**On screen:** technical report, Appendix A.4 (trace (c)) (or the trace of the simulated pan): "camera moves 190 px/s, zoom changes 30 %, lines fit 33 %: refuse".

**Say:** "Gaffer is also built to refuse. When I turned real drone frames into a panning, zooming crop, OpenCV measured the camera motion, and the agent refused to alert. Broadcast footage and panning cameras are not supported, by design."

### 10. Architecture, results, limits, AWS, close (4:25–4:45)

**On screen:** `docs/architecture.png` (dark version, 16:9, readable at 1080p), then the results table from the technical report: one-shot 34 false alerts vs agent 9 (32 of 38 real changes kept).

**Say:** "On ten held-out synthetic matches, alerting on every candidate gives thirty-four false alerts; the verified agent gives nine, and keeps thirty-two of thirty-eight real changes. Honestly: the rules make the decisions, the language model orchestrates and explains. And the real evidence is one match and one other ground. It all runs on EC2 with Bedrock, S3 and CloudWatch, using an IAM role. Gaffer: a tactical analyst that checks its own eyes before it speaks. Thank you."

*(Word count of everything in "Say" is about 650. If you run over 5:00, cut section 7 first, then the last sentence of section 8.)*

## Shot list

| # | Shot | Source | Length |
|---|---|---|---|
| 1 | Landing page hero; name card | `/`; a plain title slide | 0:20 |
| 2 | Landing scroll | `/` | 0:25 |
| 3 | Live analysis setup, replay at 4× | `/app` → Live analysis | 0:45 |
| 4 | 16:30 candidate "checking"; shape timeline | `/app` | 0:35 |
| 5 | Agent trace panel (R0 to R2) | candidate card → how I checked this | 0:45 |
| 6 | Evidence image, Approve | alert card at 18:05 | 0:30 |
| 7 | Chat answer and refusal | chat drawer | 0:20 |
| 8 | Zenodo sample: card with credit, pitch step, result | `/app` → Upload | 0:30 |
| 9 | Refused pan trace | `docs/TECHNICAL_REPORT.md` Appendix A.4 (trace (c)) | 0:15 |
| 10 | Architecture diagram; results table; closing card | `docs/architecture.png` (dark); `docs/TECHNICAL_REPORT.md` §6.3 (Table 4) | 0:20 |

Rehearse once with a stopwatch. The replay starts at 15:00, so 16:30 is 90 s of video time away and 18:05 is 185 s away; at 4× that is about 23 s and 46 s. Cut between shots rather than waiting.

## Recording checklist (Windows, free tools only)

- [ ] **Tools:** OBS Studio (screen and microphone capture; GPL, free), Audacity (noise removal for the voice; GPL, free), Shotcut or DaVinci Resolve Free (cutting; no watermark), Windows Snipping Tool for stills. No stock music, no sound effects.
- [ ] **Screen:** 1920×1080, 30 fps, browser at 100 % zoom, dark theme, full-screen (F11). Hide the bookmarks bar and personal tabs; use a clean browser profile.
- [ ] **Privacy:** close email, chat, notifications (Focus assist on), anything with names or messages. No webcam. Check that no frame shows your AWS account id, keys or the console. The URL bar showing the public IP is fine.
- [ ] **Content:** the footage is TeamTrack and Zenodo only; credits visible once on the upload step (Scott et al., TeamTrack, MIT; Synowiec, Nowak, Kamola, CC BY 4.0). No faces, no jersey numbers read out, no identification of any person.
- [ ] **Audio:** quiet room, microphone 20 cm away, a test recording first, speak 10 % slower than feels natural. Record the voice in one take per section so you can redo a single section.
- [ ] **Take:** record the screen and the voice together with OBS (one scene, one mic), one section at a time; keep 1 s of silence at each cut.
- [ ] **Edit:** trim, join, add a plain text title and closing card. No music. Burn in captions only if time allows (Shotcut text filter); otherwise upload an SRT.
- [ ] **Length check:** the exported file is under 5:00. Export H.264 MP4, 1080p.
- [ ] **Upload:** YouTube (or Vimeo), public or unlisted but viewable without login; paste the link into Devpost and into the README (`TBD-VIDEO`).
- [ ] **Last check:** watch the whole export once at normal speed with the sound on.
