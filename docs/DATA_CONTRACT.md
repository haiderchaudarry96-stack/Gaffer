# Data Contract

This is the backbone of Gaffer. **Freeze it in Phase 1 and do not change it afterwards** without explicitly flagging the migration cost.

Three producers emit `MatchState`, identically:
- `scripts/make_synthetic_match.py` (no video, has ground truth) → `source: "synthetic"`
- `src/gaffer/perception/pipeline.py` (real video, OpenCV 5) → `source: "video"`
- `scripts/teamtrack_to_matchstate.py` (TeamTrack ground-truth boxes + team IDs, projected with the **same** homography as the pipeline) → `source: "annotation"`. This is the **oracle**: running the tactics engine on it and on the pipeline output, for the same clip, shows exactly how much accuracy perception loses.

Consumers never know which producer made it:
- the tactics engine → emits `TacticalTimeline` (with **candidate** changes)
- the agent → reads `TacticalTimeline` through tools, and asks perception to look again through **vision tools**

---

## Coordinate system

- Pitch size comes from the `pitch` block (default **105 m × 68 m**; TeamTrack's real pitch size goes in config after Phase 0 inspection; futsal would be ~40 × 20 m). Coordinates below assume 105 × 68 for illustration. Origin `(0, 0)` is the **bottom-left corner**; `x` along the length (0–105), `y` along the width (0–68).
- Coordinates are **always metres on the real pitch**, never pixels.
- Raw coordinates are stored as captured. **Attacking-direction normalisation happens in the tactics engine**, not in the data.
- A point more than 5 m outside the pitch is a bad projection: dropped, not clamped.

---

## `MatchState`

```jsonc
{
  "contract_version": "1.0",
  "match_id": "teamtrack_top_01",
  "source": "video",                  // "synthetic" | "video" | "annotation"
  "fps": 5.0,                         // sampling rate of the frames array, not the source video
  "duration_s": 600.0,
  "pitch": { "length_m": 105.0, "width_m": 68.0 },

  "source_video": {                   // null for synthetic; needed so vision tools can re-analyse a window
    "uri": "s3://gaffer-clips/teamtrack_top_01.mp4",   // or a local path in dev
    "native_fps": 30.0,
    "width": 1920,
    "height": 1080
  },

  "teams": {
    "home": { "name": "Blue", "colour": "#1e5fbf", "attacking_direction_first_half": "right" },
    "away": { "name": "Red",  "colour": "#c0392b", "attacking_direction_first_half": "left" }
  },

  "periods": [
    { "name": "first_half",  "start_s": 0.0,   "end_s": 300.0 },
    { "name": "second_half", "start_s": 300.0, "end_s": 600.0 }
  ],

  "frames": [
    {
      "t": 12.40,                     // seconds from kickoff
      "players": [
        {
          "track_id": 7,
          "team": "home",             // "home" | "away" | "referee" | "unknown"
          "role": "outfield",         // "outfield" | "goalkeeper"
          "x": 42.1, "y": 18.9,
          "confidence": 0.93,
          "interpolated": false
        }
      ],
      "ball": { "x": 50.2, "y": 34.0, "visible": true },
      "possession": "home",           // "home" | "away" | "contested" | "dead" | null
      "quality": {                    // optional for synthetic, required for video
        "players_detected": 17,
        "homography_ok": true,
        "reprojection_error_m": 0.8,
        "camera_cut": false
      }
    }
  ],

  "meta": {
    "generator": "perception.pipeline v1.0",
    "opencv_version": "5.0.0",
    "created_utc": "2026-10-14T09:00:00Z",
    "notes": ""
  }
}
```

### Rules

- `frames` sorted by `t`, ascending, no duplicates.
- A frame may contain **fewer than 22 players**. Consumers must never assume a full squad.
- `track_id` stable within a match where possible; a re-found player with a new id is acceptable.
- `team: "unknown"` players are ignored by consumers, never guessed.
- `ball` may be `null` or `visible: false`; `possession` may be `null`.
- Validate with pydantic on load. Invalid files are rejected loudly.

### Ground truth

- **Synthetic:** `data/synthetic/ground_truth.json`, read **only** by `scripts/eval_synthetic.py` and `scripts/eval_agent.py`.
- **TeamTrack:** the original annotation CSVs (boxes + team IDs per frame) and the oracle `MatchState` built from them, read **only** by `scripts/eval_real.py` and `scripts/eval_agent.py`. Formation "truth" for a real clip = the tactics engine's output on the oracle `MatchState`.
- **Other real clips (optional):** `data/labels/<match_id>.json`, hand-labelled, same consumers.

```jsonc
{
  "match_id": "synthetic_001",
  "formations": [
    { "team": "home", "from_s": 0.0,    "to_s": 3690.0, "formation": "4-3-3" },
    { "team": "home", "from_s": 3690.0, "to_s": 5400.0, "formation": "4-4-2" }
  ],
  "changes": [ { "team": "home", "t": 3690.0, "from": "4-3-3", "to": "4-4-2" } ]
}
```

For the real clip, `formations` can be point labels instead: `{ "team": "home", "t": 125.0, "formation": "4-4-2" }`.

---

## `TacticalTimeline` — what the agent reads

Deliberately **small**. The LLM never sees `MatchState`.

```jsonc
{
  "contract_version": "1.0",
  "match_id": "teamtrack_top_01",
  "teams": { "home": "Blue", "away": "Red" },

  "segments": [
    {
      "start_s": 0.0, "end_s": 120.0,
      "home": {
        "formation": "4-4-2", "confidence": 0.81,
        "defensive_line_m": 38.2, "compactness_m": 24.1, "width_m": 46.5,
        "centroid": { "x": 48.3, "y": 34.2 },
        "pressing_index": 0.62
      },
      "away": { "...": "same shape" },
      "possession_pct": { "home": 61, "away": 39 },
      "players_visible_mean": { "home": 8.4, "away": 7.9 }
    }
  ],

  "events": [
    {
      "id": "evt_003",
      "t": 362.0,
      "type": "shape_change",         // "shape_change" | "line_drop" | "press_trigger"
      "team": "home",
      "from": "4-4-2", "to": "3-5-2",
      "confidence": 0.58,
      "evidence": "back line lost one player, midfield gained one; sustained 24s",
      "status": "candidate",          // "candidate" | "confirmed" | "rejected" | "uncertain"
      "verification": null            // filled by the agent, see below
    }
  ],

  "quality": {
    "uncertain_fraction": 0.12,
    "mean_players_visible": 8.2,
    "warnings": ["camera cut at 204s"]
  }
}
```

After the agent handles an event, `verification` looks like:

```jsonc
{
  "decided_by": "agent",
  "decision": "confirmed",            // "confirmed" | "rejected" | "uncertain"
  "reason": "re-analysis at 10 fps kept 3-5-2 for 41s with 19 players visible",
  "tool_calls": ["check_frame_quality", "reanalyse_window", "render_evidence"],
  "evidence_image": "s3://gaffer-outputs/teamtrack_top_01/evt_003.png",
  "trace_id": "trace_0007"
}
```

### Rules

- Segments never span a formation change — a change splits the segment.
- `confidence` 0.0–1.0. Below the configured threshold the formation is `"uncertain"`, never guessed.
- `evidence` and `reason` are short strings the agent can quote. **This is how citations stay honest.**
- Whole timeline for a 90-minute match **under ~8 KB**.

---

## `alerts.jsonl` — what the coach sees and approves

One JSON object per line:

```jsonc
{
  "alert_id": "alr_002",
  "event_id": "evt_003",
  "created_utc": "2026-10-20T10:01:00Z",
  "match_time_s": 362.0,
  "title": "Blue switched to a back three (4-4-2 → 3-5-2)",
  "explanation": "Their left-back now pushes into midfield; your right wing has space behind him.",
  "suggestion": "Ask your right winger to stay high and wide.",
  "evidence_image": "s3://gaffer-outputs/teamtrack_top_01/evt_003.png",
  "status": "pending",                // "pending" | "approved" | "rejected"
  "decided_utc": null,
  "coach_note": null
}
```

---

## Versioning

All files carry `"contract_version": "1.0"`. If the contract must change, bump it and make the loader reject mismatched versions with a clear message.
