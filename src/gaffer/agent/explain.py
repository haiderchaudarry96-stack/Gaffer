"""Coach-facing explanation of a decided candidate (build step 7; AGENT_DESIGN §5).

The decision and its reason are code (`verify` + `Toolbox.recorded_reason`); this module only
words them for a coach. Nova gets the code-written reason and the key numbers of the candidate's
tool results (`facts`) - never the engine's evidence string, whose "held 20s" it used to copy,
nor the label strip it used to paraphrase (FAILURE_LOG 17 Oct) - and writes 1-2 sentences.
`check` flags a text that contradicts the decision, gives another cause, uses a number that is
not in the facts, or mentions data the drone pipeline cannot see. A flagged text, an LLM error
or a spent budget falls back to `template`, written by code from the same facts. The rules arm
(no LLM) always gets the template.

This is a separate conversation after `record_decision`: the orchestration conversation, its
prompt and its budget are unchanged, so no decision can depend on it. Settings:
`presentation.explain` in config.yaml (outside the frozen `agent` block).
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from gaffer.agent.tools import CLOCK_RE, REF_RE, CandidateState, Toolbox, clock
from gaffer.llm.bedrock_client import BedrockError, user_message
from gaffer.tactics.events import describe_lines

EXPLAIN_SYSTEM = """You explain to a football coach a decision that code has already made about \
a possible change of team shape. The decision and its code_reason are final and true.

Write 1-2 short sentences in plain football words: name the team (FACTS.event.team), say what \
the team did and why the change is confirmed, rejected or left uncertain, following code_reason \
and cause. Do not talk about code, rules or "the decision" itself. Do not add claims FACTS do \
not state (for example which other shape the team used instead).
- Use only numbers that appear in FACTS, copied as written. Do not compute, round or convert \
numbers. For match time use the mm:ss clocks given (onset, detected, went_back_at, \
earlier_change.onset), never vague times such as "a few seconds" or "briefly".
- Cite the result each statement comes from as [R0], [R1], ... (the keys of FACTS.results).
- Do not contradict the decision and do not give another cause. Do not mention the ball, \
possession, pressing or any confidence score. No advice.
- Reply with the explanation only.

Terms in FACTS.results: new_shape_pct = share of the clear formation readings after detection \
that show the new shape; clear_readings_after = how many clear readings there were; \
went_back_s_after_detection / went_back_at = the team was back in the old shape this many \
seconds after the change was detected / at this clock; \
undoes = this change only reverses that earlier change; coverage_pct = share of frames showing \
enough of the team (see coverage_means); video_after_detection_s = seconds of video after the \
change was detected."""

#: plain-words rule behind each cause (numbers come from config)
RULES = {
    "held": "confirmed when the new shape is in at least {confirm_pct}% of at least "
            "{min_clear_readings} clear readings in the {lookahead_s} s after detection and the "
            "team does not go back",
    "cautious": "the checks allowed a confirmation; it was recorded as uncertain to be careful",
    "persistence": "rejected when the new shape is in {reject_pct}% or less of the clear "
                   "readings in the {lookahead_s} s after detection",
    "revert": "rejected when the team goes back to the old shape within {lookahead_s} s of "
              "detection",
    "return_leg": "rejected when the change only undoes an earlier change of the same team "
                  "within {lookahead_s} s: a there-and-back is not a new shape",
    "footage": "uncertain when less than {min_video_pct}% of the {lookahead_s} s after "
               "detection is on video",
    "camera": "uncertain when the camera moves, zooms or cuts: positions on the pitch are then "
              "not valid",
    "experimental_camera": "the {view} camera is experimental: its changes are at most "
                           "uncertain and never alerted",
    "inconclusive": "uncertain when the new shape is in between {reject_pct}% and "
                    "{confirm_pct}% of the clear readings, or there are fewer than "
                    "{min_clear_readings}",
}

#: words that must appear for each cause (the explanation has to name the code's cause); for
#: held / persistence / inconclusive the decisive share ("91%") also names it
_CAUSE_WORDS = {
    "held": r"\b(held|holds|kept|keeps|stayed|stays|stuck|persist\w*|sustain\w*|remain\w*|"
            r"lasted|maintain\w*|confirm\w*)\b",
    "cautious": r"\b(caution\w*|careful|uncertain)\b",
    "persistence": r"\b(only|just|merely|less than|under)\b|\b(not|never|didn't|failed to)\b"
                   r".{0,30}\b(hold|held|last|lasted|kept|keep|stick|stay|stayed|persist\w*|"
                   r"sustain\w*)\b",
    "revert": r"\b(revert\w*|went back|go(?:es|ing)? back|back to|switched back|returned)\b",
    "return_leg": r"\b(return\w*|back to|went back|go(?:es|ing)? back|undo\w*|revers\w*|"
                  r"revert\w*)\b",
    "footage": r"\b(footage|clip|video|record\w*|look-?ahead)\b|\bends?\b|"
               r"\bnot enough (play|time)\b",
    "camera": r"\b(camera|pan\w*|zoom\w*|moving|moved|lines?|geometry|cut)\b",
    "experimental_camera": r"\bexperimental\b|\bside (camera|view)\b",
    "inconclusive": r"\b(inconclusive|unclear|not enough|too few|undecided|could not|"
                    r"couldn't|cannot|budget|neither|between)\b",
}
#: "the new shape did not hold" in any wording
_NOT_HELD = [
    r"\b(not|never|no longer|n't)\s+(\w+\s+){0,2}(held|hold|last\w*|persist\w*|sustain\w*|kept|"
    r"stay\w*|stable|maintain\w*)\b",
    r"\bno (sustained|lasting|stable|persistent|real|actual|clear)\b",
    r"\b(unstable|fluctuat\w*|short-lived|flip-?flop\w*)\b",
    r"\bno (transition|change|switch)\b",
]
_UNAVAILABLE = r"\b(ball|possession|pressing|press)\b"
_CONFIDENCE = r"\bconfidence\b"
#: a claim preceded (within 20 characters) by one of these is negated or hypothetical
_NEGATION = re.compile(r"\b(not|n't|cannot|never|no|without|to|would|needed|needs|need)\b"
                       r"[^.]{0,20}$")

FORMATION_RE = re.compile(r"\b\d(?:-\d){1,4}\b")
EVENT_RE = re.compile(r"\bevt_\d{3}\b")
BARE_REF_RE = re.compile(r"\bR\d+\b")
NUM_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")
_UNITS = (("pct", re.compile(r"\s*(%|percent\b|per cent\b)", re.I)),
          ("px", re.compile(r"\s*px", re.I)),
          ("fps", re.compile(r"\s*fps\b", re.I)),
          ("min", re.compile(r"\s*(min|mins|minutes?)\b", re.I)),
          ("s", re.compile(r"\s*(s|sec|secs|seconds?)\b", re.I)),
          ("count", re.compile(r"\s+(?:[a-z-]+\s+){0,2}(windows?|readings?|frames?|players?)\b",
                               re.I)))


def pct(x: float | None) -> int | None:
    return None if x is None else int(round(100 * float(x)))


# --------------------------------------------------------------------------- facts


def cause_of(tb: Toolbox, st: CandidateState) -> str:
    """Which rule decided the candidate (the code's cause the explanation must name)."""
    v, dec = st.verdict, st.decision
    capped = tb.ctx.vcfg.max_decision(tb.ctx.view) != "confirmed"
    if v.verdict == "refuse":
        return "camera"
    if capped and dec == "uncertain":
        return "experimental_camera"
    if "footage" in v.failed:
        return "footage"
    if v.verdict == "reject":
        ev = st.latest
        if ev.return_of is not None:
            return "return_leg"
        return "revert" if ev.reverted_after_s is not None else "persistence"
    if v.verdict == "confirm":
        return "held" if dec == "confirmed" else "cautious"
    return "inconclusive"


def _drop_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


def _pass_facts(source: str, ev: Any, look: float, t_det: float) -> dict[str, Any]:
    """Key numbers of one pass (PassEvidence or a re-analysis `vs_event` dict)."""
    g = ev.get if isinstance(ev, dict) else (lambda k: getattr(ev, k))
    share = g("after_share_new") if isinstance(ev, dict) else g("share_new")
    rev = g("reverted_after_s")
    return _drop_none({
        "source": source, "new_shape_pct": pct(share),
        "clear_readings_after": g("confident_after"),
        "went_back_s_after_detection": None if rev is None else int(round(rev)),
        "went_back_at": None if rev is None else clock(t_det + float(rev)),
        "undoes": g("return_of"),
        "coverage_before_pct": pct(g("coverage_before")),
        "coverage_after_pct": pct(g("coverage_after")),
        "video_after_detection_s": int(round(float(g("footage_frac")) * look)),
    })


def _window(r: dict[str, Any]) -> str | None:
    w = r.get("window")
    return f"{clock(w[0])}-{clock(w[1])}" if w else None


def _quality_facts(r: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    video = r.get("backend") == "video"
    shift = r.get("camera_shift_px_per_s_max")
    zoom = r.get("zoom_change_max")
    out = {"source": "OpenCV camera check on the video" if video
           else "camera check (no video: stored positions)",
           "window": _window(r), "pitch_lines_fit_pct": pct(r.get("homography_ok_share")),
           "camera_cut": r.get("camera_cut"),
           "coverage_pct": {names[s]: pct(c) for s, c in (r.get("coverage") or {}).items()
                            if c is not None},
           "problems": r.get("problems") or None}
    if video:
        out["camera_shift_px_per_s"] = shift
        out["zoom_change_pct"] = None if zoom is None else round(100 * float(zoom), 1)
    return _drop_none(out)


def _reanalysis_facts(r: dict[str, Any], names: dict[str, str], look: float, t_det: float
                      ) -> dict[str, Any]:
    video = r.get("backend") == "video"
    src = ("OpenCV second look: perception re-run on the video" if video
           else "second look: tactics re-run on the stored positions")
    vs = r.get("vs_event")
    out = _pass_facts(src, vs, look, t_det) if vs else {"source": src}
    out["window"] = _window(r)
    if video:
        out["fps"] = r.get("sample_fps")
    if not vs:
        out["coverage_pct"] = {names[s]: pct(c) for s, c in (r.get("coverage") or {}).items()
                               if c is not None}
    return _drop_none(out)


def decisive_ref(st: CandidateState) -> str:
    """The pass whose evidence the verdict used: the last re-analysis covering the required
    span (latest pass wins), else the first pass (R0)."""
    refs = [ref for ref, info in st.refs.items() if info.ok and info.tool == "reanalyse_window"
            and (st.results.get(ref, {}).get("vs_event") or {}).get("covers_required_span")]
    return refs[-1] if refs and st.second_look else "R0"


def facts(tb: Toolbox, st: CandidateState) -> dict[str, Any]:
    """What the explanation may use: the decision, the code reason, the rule behind it and the
    key numbers of the candidate's tool results by ref (nothing else; no engine evidence)."""
    c, ctx, v = st.cand, tb.ctx, tb.ctx.vcfg
    look = int(round(v.lookahead_s))
    names = {"home": tb.team_name("home"), "away": tb.team_name("away")}
    cause = cause_of(tb, st)
    thresholds = {"confirm_pct": pct(v.persist_pass), "reject_pct": pct(v.persist_fail),
                  "min_clear_readings": v.min_confident_windows,
                  "min_video_pct": pct(v.min_footage_frac), "lookahead_s": look}
    results: dict[str, dict[str, Any]] = {
        "R0": _pass_facts("first pass: tactics engine on the stored positions", st.first, look,
                          c.detected_at_s)}
    refused: list[str] = []
    for ref, info in st.refs.items():
        if info.tool not in ("check_frame_quality", "reanalyse_window"):
            continue
        r = st.results.get(ref)
        if r is None:
            continue
        if "error" in r:
            if r["error"] in ("over_budget", "vision_error", "no_video"):
                results[ref] = {"source": f"{info.tool} (OpenCV)", "refused": r.get("message")}
                refused.append(ref)
            continue
        results[ref] = (_quality_facts(r, names) if info.tool == "check_frame_quality"
                        else _reanalysis_facts(r, names, look, c.detected_at_s))
    decisive = decisive_ref(st)
    quality = [ref for ref, info in st.refs.items()
               if info.ok and info.tool == "check_frame_quality"]
    if cause == "footage":
        cite = ["R0"]
    elif cause == "camera":
        cite = quality[-1:] or [st.verdict_ref]
    elif cause == "experimental_camera":
        cite = [decisive] + refused[-1:]
    else:
        cite = [decisive if decisive in results else "R0"]
    out: dict[str, Any] = {
        "event": {"id": c.id, "team": names[c.team], "from": c.from_, "to": c.to,
                  "lines": describe_lines(c.from_, c.to), "onset": clock(c.t),
                  "detected": clock(c.detected_at_s)},
        "decision": st.decision, "cause": cause, "code_reason": st.reason,
        "rule": RULES[cause].format(view=ctx.view or "this", **thresholds),
        "thresholds": thresholds, "reading_window_s": int(round(ctx.tcfg.window_s)),
        "coverage_means": f"frames showing at least {ctx.tcfg.min_players} outfield players "
                          "of the team",
        "decisive": decisive, "cite": cite, "view": ctx.view, "results": results,
    }
    ret = st.latest.return_of
    if ret is not None:
        p = next((x for x in ctx.candidates if x.id == ret), None)
        out["earlier_change"] = ({"id": p.id, "from": p.from_, "to": p.to, "onset": clock(p.t)}
                                 if p is not None else {"id": ret, "from": c.to, "to": c.from_})
    return out


# --------------------------------------------------------------------------- template


def template(f: dict[str, Any]) -> str:
    """Explanation written by code from the facts (always true; the fallback)."""
    e, cause, look = f["event"], f["cause"], f["thresholds"]["lookahead_s"]
    team, old, new = e["team"], e["from"], e["to"]
    d = f["results"].get(f["decisive"], {})
    share, k = d.get("new_shape_pct"), d.get("clear_readings_after")
    refs = "".join(f"[{r}]" for r in f["cite"])
    second = (f" (second look with OpenCV at {d['fps']:g} fps)"
              if d.get("fps") is not None else "")
    th = f["thresholds"]
    if cause == "held":
        return (f"{team} kept the {new} after {e['onset']}: it showed in {share}% of {k} clear "
                f"formation readings over the next {look} s, with no return to {old}{second} "
                f"{refs}.")
    if cause == "cautious":
        return (f"The checks would allow a confirmation ({new} in {share}% of {k} clear "
                f"readings over {look} s), but it was kept as uncertain to be careful {refs}.")
    if cause == "persistence":
        return (f"{team}'s {new} did not last: after {e['onset']} it showed in only {share}% of "
                f"{k} clear formation readings over the next {look} s{second} {refs}.")
    if cause == "revert":
        return (f"{team} went back to {old} at {d.get('went_back_at')}, "
                f"{d.get('went_back_s_after_detection')} s after the switch to {new} was "
                f"detected, so the change did not last{second} {refs}.")
    if cause == "return_leg":
        p = f.get("earlier_change") or {}
        held = (f", even though the {new} then showed in {share}% of {k} clear readings"
                if share is not None and share >= th["confirm_pct"] else "")
        when = f" at {p['onset']}" if p.get("onset") else ""
        return (f"This is {team} going back to {new} after their switch {p.get('from')} -> "
                f"{p.get('to')}{when} ({p.get('id')}): a there-and-back is not alerted as a new "
                f"shape{held} {refs}.")
    if cause == "footage":
        s = f["results"]["R0"].get("video_after_detection_s")
        return (f"Not enough video to check it: the clip ends {s} s after the change was "
                f"detected, and {look} s are needed to see whether the {new} lasts {refs}.")
    if cause == "camera":
        q = f["results"].get(f["cite"][0], {})
        probs = ", ".join(q.get("problems") or []) or "camera checks failed"
        return (f"The camera moved or cut ({probs}), so positions on the pitch are not valid "
                f"and no formation was read {refs}.")
    if cause == "experimental_camera":
        out = (f"Experimental camera: changes seen by the {f['view']} camera are never "
               "alerted.")
        refused = [f["results"][r]["refused"] for r in f["cite"]
                   if "refused" in f["results"].get(r, {})]
        if refused:
            out += (f" The second look was refused as too slow ({refused[0]}), and the first "
                    f"pass is inconclusive ({share}% of {k} clear readings) {refs}.")
        elif share is not None:
            out += f" The {new} showed in {share}% of {k} clear readings {refs}."
        else:
            out = out[:-1] + f" {refs}."
        return out
    if k is None or share is None or k < th["min_clear_readings"]:
        return (f"Too few clear formation readings after the change ({k or 0}) to decide "
                f"{refs}.")
    return (f"Inconclusive: the {new} showed in {share}% of {k} clear formation readings, "
            f"between the {th['reject_pct']}% needed to reject and the {th['confirm_pct']}% "
            f"needed to confirm {refs}.")


# --------------------------------------------------------------------------- check


@dataclass
class Allowed:
    """Numbers (by unit) and clocks (match seconds) present in the facts."""

    by_unit: dict[str, set[float]] = field(default_factory=dict)
    clocks: set[int] = field(default_factory=set)

    def add(self, unit: str, v: float) -> None:
        self.by_unit.setdefault(unit, set()).add(float(v))
        self.by_unit.setdefault("any", set()).add(float(v))


def _unit_at(text: str, end: int) -> str:
    rest = text[end:end + 40]
    for unit, rx in _UNITS:
        if rx.match(rest):
            return unit
    return "any"


def _scan(text: str) -> tuple[list[tuple[float, int, str]], list[int]]:
    """(numbers with their decimals and unit, clocks in seconds) of a text; formations, refs
    and event ids are not numbers."""
    clocks = [int(m) * 60 + int(s) for m, s in CLOCK_RE.findall(text)]
    t = CLOCK_RE.sub(" ", text)
    for rx in (FORMATION_RE, EVENT_RE, REF_RE, BARE_REF_RE):
        t = rx.sub(" ", t)
    nums = []
    for m in NUM_RE.finditer(t):
        tok = m.group(0)
        dec = len(tok.split(".")[1]) if "." in tok else 0
        nums.append((float(tok), dec, _unit_at(t, m.end())))
    return nums, clocks


#: unit of a numeric fact by its key (first match wins: px_per_s before _s)
_KEY_UNITS = (("_px_per_s", "px"), ("_pct", "pct"), ("_s", "s"), ("fps", "fps"),
              ("clear_readings_after", "count"), ("min_clear_readings", "count"))


def _unit_of(key: str) -> str:
    return next((u for suffix, u in _KEY_UNITS if key.endswith(suffix)), "any")


def allowed_numbers(f: dict[str, Any]) -> Allowed:
    """Every number and clock that appears in the facts, keyed by unit."""
    out = Allowed()

    def walk(key: str, v: Any, unit: str | None = None) -> None:
        if isinstance(v, dict):  # values of a "*_pct" dict ({"White": 84}) are percentages
            for k, x in v.items():
                walk(k, x, "pct" if key.endswith("_pct") else None)
        elif isinstance(v, list):
            for x in v:
                walk(key, x, unit)
        elif isinstance(v, bool) or v is None:
            return
        elif isinstance(v, int | float):
            out.add(unit or _unit_of(key), v)
        elif isinstance(v, str):
            nums, clocks = _scan(v)
            out.clocks.update(clocks)
            for x, _, u in nums:
                out.add(u, x)

    walk("", f)
    for s in list(out.by_unit.get("s", ())):
        if s % 60 == 0:
            out.add("min", s / 60)
    return out


def _matches(x: float, dec: int, values: set[float]) -> bool:
    return any(round(v, dec) == x for v in values)


def _unnegated(rx: str, low: str) -> re.Match[str] | None:
    """The first match of `rx` in `low` that is not negated / hypothetical just before it."""
    for m in re.finditer(rx, low):
        if not _NEGATION.search(low[:m.start()]):
            return m
    return None


def check(text: str, f: dict[str, Any], cfg: dict[str, Any]) -> list[str]:
    """Problems of an explanation against its facts (empty: acceptable). Cheap and strict:
    a flagged text is replaced by the template, which is always true."""
    p = cfg["presentation"]["explain"]
    t = text.strip()
    if not t:
        return ["empty"]
    probs: list[str] = []
    low = t.lower()
    if len(t) > int(p["max_chars"]):
        probs.append(f"longer than {p['max_chars']} characters")
    sentences = len(re.findall(r"[.!?](?=\s|$)", t)) + (0 if re.search(r"[.!?]\s*$", t) else 1)
    if sentences > int(p["max_sentences"]):
        probs.append(f"{sentences} sentences > {p['max_sentences']}")
    unknown = sorted({r for r in REF_RE.findall(t) if r not in f["results"]})
    if unknown:
        probs.append(f"cites results that do not exist: {', '.join(unknown)}")
    m = re.search(_UNAVAILABLE, low)
    if m:
        probs.append(f"mentions unavailable data: {m.group(0)}")
    if re.search(_CONFIDENCE, low):
        probs.append("mentions a confidence score (not a cause of the decision)")
    # numbers and clocks must come from the facts
    ok = allowed_numbers(f)
    slack = float(p["time_slack_s"])
    nums, clocks = _scan(t)
    for s in clocks:
        if not any(abs(s - c) <= slack for c in ok.clocks):
            probs.append(f"clock {s // 60}:{s % 60:02d} is not in the results")
    for x, dec, unit in nums:
        pool = ok.by_unit.get(unit, set()) if unit != "any" else ok.by_unit.get("any", set())
        if unit == "count":
            pool = pool | ok.by_unit.get("any", set())
        if not _matches(x, dec, pool):
            shown = f"{x:g}" + {"pct": "%", "s": " s", "fps": " fps", "min": " min",
                                "px": " px"}.get(unit, "")
            probs.append(f"number {shown} is not in the results")
    # the cause and the decision must be the code's
    cause, dec = f["cause"], f["decision"]
    d = f["results"].get(f["decisive"], {})
    share = d.get("new_shape_pct")
    named = re.search(_CAUSE_WORDS[cause], low) or (
        cause in ("held", "persistence", "inconclusive") and share is not None
        and re.search(rf"\b{share}\s*%", low))
    if not named:
        probs.append(f"does not name the cause ({cause})")
    held = (share or 0) >= f["thresholds"]["confirm_pct"]
    if dec == "confirmed" or cause == "inconclusive" or (
            held and cause in ("return_leg", "footage", "experimental_camera", "cautious")):
        for rx in _NOT_HELD:
            mm = re.search(rx, low)
            if mm:
                probs.append(f"says the new shape did not hold ('{mm.group(0)}'), which the "
                             "results do not show")
                break
    if dec == "confirmed" and _unnegated(r"\b(reject\w*|uncertain|revert\w*|went back)\b", low):
        probs.append("contradicts the confirmation")
    if dec != "confirmed" and cause != "cautious" and _unnegated(r"\bconfirm(s|ed|ing)?\b",
                                                                  low):
        probs.append("claims a confirmation")
    if cause == "persistence" and d.get("went_back_at") is None and _unnegated(
            r"\b(revert\w*|went back|switched back)\b", low):
        probs.append("says the team went back, but no return to the old shape was found")
    if cause != "return_leg" and "undoes" not in d and _unnegated(r"\bundo\w*\b", low):
        probs.append("says it undoes an earlier change, but it does not")
    return probs


# --------------------------------------------------------------------------- explainer


@dataclass
class Explanation:
    text: str
    source: str  # "agent" (checked model text) | "template"
    flags: list[str] = field(default_factory=list)  # why the model's text was replaced
    raw: str | None = None  # the model's text when it was replaced
    llm: dict[str, Any] | None = None  # model, tokens, latency of the call
    cost_usd: float = 0.0


def _clean(text: str) -> str:
    t = text.strip().strip('"').strip()
    t = re.sub(r"^(explanation|answer)\s*:\s*", "", t, flags=re.I)
    return re.sub(r"\s+", " ", t)


def prompt(f: dict[str, Any]) -> str:
    """The user message: the facts as compact JSON (internals left out; the thresholds are in
    the rule text)."""
    shown = {k: v for k, v in f.items() if k not in ("decisive", "thresholds")}
    return "FACTS:\n" + json.dumps(shown, separators=(",", ":"))


class Explainer:
    """Writes the explanation of a decided candidate: Nova + `check`, else `template`."""

    def __init__(self, cfg: dict[str, Any], llm: Any | None = None, limiter: Any | None = None,
                 max_cost_usd: float | None = None) -> None:
        self.cfg = cfg
        self.p = cfg["presentation"]["explain"]
        self.llm = llm if bool(self.p["use_llm"]) else None
        self.limiter = limiter
        self.model = cfg["bedrock"]["model_id"]
        self.prices = cfg["agent"]["llm"]["prices_per_1k"]
        self.max_cost = (float(max_cost_usd) if max_cost_usd is not None
                         else float(self.p["max_cost_usd_per_run"]))
        self.calls, self.cost, self.tokens = 0, 0.0, Counter()
        self.flagged = 0

    def _price(self, tin: int, tout: int) -> float:
        pin, pout = self.prices.get(self.model, (0.0, 0.0))
        return tin / 1000 * float(pin) + tout / 1000 * float(pout)

    def explain(self, f: dict[str, Any], use_llm: bool = True, purpose: str = "explain"
                ) -> Explanation:
        tpl = template(f)
        if self.llm is None or not use_llm:
            return Explanation(tpl, "template")
        worst = self._price(3000, int(self.p["max_tokens"]))
        if self.cost + worst > self.max_cost:
            return Explanation(tpl, "template", [f"explanation budget ${self.max_cost} spent"])
        if self.limiter is not None:
            self.limiter.wait()
        t0 = time.perf_counter()
        try:
            r = self.llm.chat([user_message(prompt(f))], system=EXPLAIN_SYSTEM,
                              model_id=self.model, max_tokens=int(self.p["max_tokens"]),
                              temperature=float(self.p["temperature"]), purpose=purpose)
        except BedrockError as exc:
            return Explanation(tpl, "template", [f"llm error: {str(exc).splitlines()[0]}"])
        tin = int(r.usage.get("input_tokens", 0))
        tout = int(r.usage.get("output_tokens", 0))
        cost = self._price(tin, tout)
        self.calls += 1
        self.cost += cost
        self.tokens.update({"in": tin, "out": tout})
        info = {"model_id": r.model_id, "in": tin, "out": tout,
                "latency_ms": round(r.latency_ms or (time.perf_counter() - t0) * 1000)}
        text = _clean(r.text)
        if text and not REF_RE.search(text):  # a missing citation is a format slip, not a lie
            text = text.rstrip(" .") + " " + "".join(f"[{x}]" for x in f["cite"]) + "."
        flags = check(text, f, self.cfg)
        if flags:
            self.flagged += 1
            return Explanation(tpl, "template", flags, text, info, cost)
        return Explanation(text, "agent", [], None, info, cost)

    def stats(self) -> dict[str, Any]:
        return {"calls": self.calls, "cost_usd": round(self.cost, 5),
                "tokens": dict(self.tokens), "flagged": self.flagged}
