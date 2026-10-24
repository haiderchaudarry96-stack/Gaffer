# Devpost submission text (draft)

Copy each section into the matching Devpost field. Plain English, no hype. Numbers are from the files named in [`TECHNICAL_REPORT.md`](TECHNICAL_REPORT.md) and cross-checked in [`FINAL_AUDIT.md`](FINAL_AUDIT.md). Placeholders: `TBD-URL` (final public link), `TBD-VIDEO` (demo video link), `TBD-REPO` (public repository link).

## Project name

Gaffer

## Elevator pitch (one line)

An AI football analyst for coaches: it watches the match with OpenCV 5, spots when a team changes shape, and checks its own eyes before it alerts you.

## Inspiration

Professional clubs pay for tactical analysis. A grassroots or university coach usually has a phone, sometimes a drone, and nobody to tell them the moment the other team switched from four at the back to three. I wanted to build the analyst a coach without a budget could have.

The harder idea was trust. A formation read from video is noisy: a free kick crowds the players, a drone drifts, a long shadow looks like a person. An assistant that raises an alert on every wobble would be ignored within a week. So the project's rule is that a detected change is only a *candidate*, and the system must look again with OpenCV and check itself before it speaks to the coach.

## What it does

- Reads a match video from a high, fixed or drone camera that sees the whole pitch.
- Finds and tracks the players with OpenCV 5, tells the two teams apart by shirt colour, and maps every player onto a 2D pitch.
- Reads each team's formation every few seconds and flags the moment a team switches shape, for example White 4-4-2 → 3-4-3 at 16:30 in the demo match.
- Sends an Amazon Bedrock agent (Nova 2 Lite) to verify each flagged change. The agent asks OpenCV whether the camera is still and the pitch is fitted, asks for a second look at a higher frame rate when the first read is thin, and then confirms, rejects or marks the change uncertain, with the reason.
- Shows the coach a pending alert with the evidence (an annotated frame and the shape before and after). **The coach approves or rejects every alert.**
- Answers questions in a chat, grounded in the stored results ("I can't answer that" when the data does not say).
- Refuses what it cannot do: broadcast footage and panning cameras are refused by design.

## How we built it

**The vision work is OpenCV 5.0.0.** The pitch is found from its painted lines (top-hat, thinning, a homography); a hovering drone is re-aligned on every frame (`cv2.phaseCorrelate`, `cv2.findTransformECC`, ORB fallback); players are detected with a classical detector on the drone view and YOLOX through `cv2.dnn` on a side view; teams come from `cv2.kmeans` on shirt colours; and a per-video self-calibration (grass and shadow model, expected player size from the homography, static-object filter) lets the same code work on a second ground. The agent's two vision tools are OpenCV too: a camera-quality check and a re-run of the whole perception pipeline on one window.

**The agent.** For every candidate shape change the agent calls the tools, reads small JSON results, and the decision comes from deterministic rules (does the new shape hold in at least 60 % of the confident windows, did the team go back, is the camera valid). The LLM chooses the window and the rate, and writes the plain-words explanation, which is checked against the facts. The model never sees pixels.

**On AWS.** One EC2 instance (Sydney) runs the FastAPI server, the OpenCV analysis worker and the React front end in one container; Amazon Bedrock runs the agent through an IAM instance role (no access keys on the server); S3 holds the large assets; CloudWatch holds the logs and two metrics; Systems Manager does the deploys.

**Built with AI coding assistants, and said plainly:** Claude Code and Codex helped write the code. I designed the system, chose the architecture and the rules, directed the work, tested it on real and synthetic footage, reviewed the results and wrote down what failed.

**Honest evaluation.** Synthetic matches give exact ground truth. On 10 held-out matches (38 real shape changes) alerting on every candidate gives 34 false alerts; the verified agent gives 9, and keeps 32 of the 38 real changes. On real footage, TeamTrack's annotations score the detection (F1 0.918 and 0.930 at 1 m on two windows) and the formations; a Zenodo clip from another pitch tests generalisation.

## Challenges we ran into

- **Formations are hard to read from video.** During a free kick only seven or eight of ten outfield players are visible, and the shape flips. In the demo match one 5-second window decided whether White's 4-4-2 before 16:30 counted.
- **The first detector worked on one overcast day and failed on a second ground.** On a Zenodo clip with low sun, shadows as long as the players and light-pole shadows across the pitch, it found 63 detections per frame for 25 real people (precision 0.40) and gave a team to 41 % of them. Per-video self-calibration lifted F1 at 1 m from 0.567 to 0.855 on the unseen part of that clip.
- **The language model did not make the decisions better.** The agent's decisions were identical to the rules-only arm's on all 68 candidates. The false-alert reduction comes from the deterministic second look. We kept the agent for what it does well (picking the window and rate, explaining, enforcing the protocol) and we say so.
- **Cloud limits.** The Free plan refused the Graviton instance, so the largest eligible type is an Intel `m7i-flex.large`; a 6-minute 4K upload took 31.5 minutes there on the 22 Oct build.
- **Honesty about low resolution.** On a 720p copy of the demo clip the main change was still found but White's formation agreement with ground truth dropped from 91.7 % to 74.1 %, so the upload page says so.
- **A missed change.** Blue's real 18:50 change is rejected as a "return leg" by a rule that is right on synthetic data. The fix added 25 false alerts there, so we left it off and listed it as a known miss.

## Accomplishments that we're proud of

- An agent whose **vision results change its next action**, with the traces to prove it: a thin first read made it re-read the window at 6 frames per second, and on real frames a measured 190 px/s camera motion made it refuse to alert at all.
- **Fewer false alerts without losing the real ones:** 34 → 9 false alerts, 32 of 38 real changes kept, at $0.021 of Bedrock per 90-minute match.
- **It generalised, measurably:** on another ground F1 from 0.567 to 0.855 and players with a team from 41 % to 95 %, with the same code and no TeamTrack-specific rules.
- A **real alert on real footage:** White 4-4-2 → 3-4-3 at 16:30, confirmed with evidence. (The demo window was chosen with ground-truth positions; we say so.)
- A **failure log** with 55 dated entries and images, including the things that did not work.
- Deployed on AWS with an instance role, CloudWatch logs and metrics, pinned dependencies and a delete-everything guide.

## What we learned

- Put the numbers first: the synthetic matches with exact ground truth let us build and measure the tactics engine and the agent before touching real video, and told us honestly what the LLM was worth.
- A check that can say "uncertain" is worth more than a model that always answers.
- Measure on a second ground early. One dataset flatters you.
- Time measurements on a busy laptop mislead: the same Zenodo run was 4.4 s per video second when idle and 13 when the machine was loaded, so we re-measure before we quote.

## What's next

- Test on more grounds and more camera heights; today the real evidence is one match and one 30-second clip of another pitch.
- Detect the ball on the drone view, so possession and pressing can join the formation reading.
- Fix the return-leg rule so a real Blue change is not missed, without adding false alerts.
- Speed up 4K analysis on the small instance and re-measure on EC2.
- A coach-facing mode for a live camera (today the "Live analysis" replays a recorded match and says so).

## Built with

OpenCV 5.0.0 (`cv2.dnn`, `kmeans`, `findHomography`, `findTransformECC`, `phaseCorrelate`, `ximgproc.thinning`, ORB, `estimateAffinePartial2D`) · Python 3.12 · FastAPI · React, Vite, Tailwind CSS · Amazon Bedrock (Nova 2 Lite) · Amazon EC2 · Amazon S3 · Amazon CloudWatch · AWS IAM · AWS Systems Manager · Docker · supervision (ByteTrack) · NumPy, SciPy, scikit-learn · TeamTrack and Zenodo datasets.

## Try it out

- Live app: http://13.210.196.109/ (final link: TBD-URL). If your browser switches to https, type `http://` yourself; if it still does not open, see the demo video.
- Demo video: TBD-VIDEO
- Code: TBD-REPO (the repository is private until the author makes it public; see `FINAL_AUDIT.md`)
- Start with: open the app → *Live analysis*; or *Upload your own video* → try the two sample clips. Each sample has a plain Download link if you would rather test with the file.
- Technical report: [`docs/TECHNICAL_REPORT.md`](TECHNICAL_REPORT.md); Agentic Vision evidence: [`docs/TECHNICAL_REPORT.md#agentic-vision-award-evidence`](TECHNICAL_REPORT.md#agentic-vision-award-evidence)

## Credits

TeamTrack: Scott et al., 2024, MIT licence. Zenodo "Soccer pitch top-view": Synowiec, Nowak, Kamola, DOI 10.5281/zenodo.14867795, CC BY 4.0.
