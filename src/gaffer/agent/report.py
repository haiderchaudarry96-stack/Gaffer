"""Coach report for one match (build step 7; AGENT_DESIGN §5).

One LLM call per match. The inputs are the **decided** events (the agent's verified findings,
with their code-written reasons) and the tactics timeline's segments (the first-pass reading),
nothing else: candidates the agent did not check are listed but cannot be cited. The report has
a formation story, each confirmed change with what it may have been trying to fix, what was not
alerted, three practical recommendations and the limits.

Grounding: every sentence that contains a number or a time cites `[evt_003]` (a decided event)
or `[seg 16:30-17:30]` (a timeline segment, or a run of consecutive ones), and every number and
clock in it must appear in the cited items. `check_report` enforces this plus exactly three
recommendations and no ball / possession / pressing (the drone pipeline cannot see them). A
failed check gets one retry with the problems listed, then the code template
(`template_report`), which is built from the same inputs and passes the same check.

    py -m gaffer.agent.report --match outputs\\match_state_top_w900_1260_4fps.json --view top \
        --decided outputs\\agent_video_step7\\explanations.json --set w900 \
        --alerts outputs\\agent_video_step7\\alerts_llm.jsonl \
        --out outputs\\agent_video_step7\\report_w900_1260 [--no-llm] [--note "..."]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from gaffer.agent.alerts import AlertStore
from gaffer.agent.context import MatchContext
from gaffer.agent.explain import Allowed, _matches, _scan, allowed_numbers
from gaffer.agent.tools import Toolbox, clock
from gaffer.config import load_config, repo_path
from gaffer.llm.bedrock_client import BedrockError, user_message
from gaffer.schema import ContractError, load_match_state
from gaffer.tactics.events import describe_lines
from gaffer.tactics.formation import UNCERTAIN, parse_formation
from gaffer.tactics.metrics import span_metrics

REPORT_SYSTEM = """You write a short tactical report for a football coach from DATA (JSON).
Return only this JSON object, no other text:
{"formation_story": ["sentence", ...],
 "changes": [{"event": "evt_...", "what_changed": "...", "may_have_fixed": "..."}],
 "not_alerted": ["sentence", ...],
 "recommendations": ["sentence", "sentence", "sentence"],
 "limits": ["sentence", ...]}

Content:
- formation_story: 2-4 sentences: how each team lined up over time, from DATA.segments.
- formation_story covers both teams, each with its main shapes and their times.
- changes: one object for each event of DATA.events with decision "confirmed", no others. \
what_changed: what the team changed and how its shape moved (the event's before / after \
numbers). may_have_fixed: a hedged guess ("may have", "possibly") of what it was meant to fix, \
built on a number that moved (e.g. width or defensive line before -> after) or on the segment \
just before the change.
- not_alerted: 1-3 sentences on the decided events that were not confirmed, and on \
DATA.not_verified (the agent did not check those: never present them as findings).
- recommendations: exactly 3 practical coaching actions (what to do on the pitch or in \
training), one sentence each, starting with a verb, each built on a cited number or time, \
e.g. "Overload the channel behind Red's back three, which was 48.0 m wide after 12:10 \
[evt_004]."
- limits: 1-2 sentences; include DATA.match.note if there is one (no citation needed).

Rules:
- Every sentence that contains a number or a mm:ss time ends with its source in brackets, \
before the full stop: [evt_003] for an event of DATA.events, [seg 16:30-17:30] for one segment \
of DATA.segments, or [seg 16:30-18:45] for consecutive segments (start of the first, end of \
the last). Cite nothing else.
- Use only numbers and times that appear in the cited items, copied as written; at most 2 \
numbers per sentence.
- Plain football words: "defensive line" (line_m: its distance from the team's own goal), \
"depth" (depth_m: front-to-back length), "width" (width_m), "share of positions in its own box" \
(own_box_pct). Never write the field names.
- The segments are the first-pass reading; only DATA.events were checked by the agent.
- Do not mention the ball, possession, pressing or confidence scores."""

CITE_RE = re.compile(r"\[(evt_\d{3}|seg \d{1,3}:\d{2}-\d{1,3}:\d{2})\]")
_UNAVAILABLE = re.compile(r"\b(ball|possession|pressing|press|confidence)\b", re.I)


def _r1(v: float | None) -> float | None:
    return None if v is None else round(float(v), 1)


# --------------------------------------------------------------------------- inputs


def _shape_numbers(tb: Toolbox, team: str, label: str, frames: list[Any], share: float | None,
                   window: str) -> dict[str, Any]:
    """Line, depth and width of one shape panel's window (the team's own back line)."""
    back = parse_formation(label)[0] if label != UNCERTAIN else None
    m = span_metrics(frames, team, tb.ctx.tcfg, back_line=back)
    return {"window": window, "formation": label, "line_m": _r1(m.defensive_line_m),
            "depth_m": _r1(m.compactness_m), "width_m": _r1(m.width_m),
            "own_box_pct": None if share is None else int(round(100 * share))}


def build_inputs(ctx: MatchContext, decided: list[dict[str, Any]],
                 alerts: dict[str, Any] | None = None, note: str | None = None
                 ) -> dict[str, Any]:
    """DATA for the report: segments (first pass) and the decided events; `decided` items have
    event_id, decision, reason (code-written) and explanation, optionally new_shape_pct /
    clear_readings_after / fps of the decisive pass. `note`: where the footage comes from
    (goes into the limits; no numbers)."""
    tb = Toolbox(ctx)  # read-only use: shape panels, team names, availability
    names = {"home": tb.team_name("home"), "away": tb.team_name("away")}
    segs = []
    for s in ctx.result.timeline.segments:
        item: dict[str, Any] = {"seg": f"{clock(s.start_s)}-{clock(s.end_s)}"}
        for side in ("home", "away"):
            t = getattr(s, side)
            item[names[side]] = {"formation": t.formation, "line_m": _r1(t.defensive_line_m),
                                 "depth_m": _r1(t.compactness_m), "width_m": _r1(t.width_m)}
        segs.append(item)
    done = {d["event_id"]: d for d in decided}
    events, not_verified = [], []
    for c in ctx.candidates:
        base = {"id": c.id, "team": names[c.team], "change": f"{c.from_} -> {c.to}",
                "onset": clock(c.t)}
        d = done.get(c.id)
        if d is None:
            not_verified.append(base)
            continue
        e = {**base, "lines": describe_lines(c.from_, c.to), "decision": d["decision"],
             "reason": d["reason"], "explanation": d.get("explanation")}
        for k in ("new_shape_pct", "clear_readings_after", "fps"):
            if d.get(k) is not None:
                e[k] = d[k]
        ret = ctx.return_of(c)
        if ret is not None and d["decision"] != "confirmed":
            p = ctx.candidate(ret)
            e["undoes"] = {"id": p.id, "change": f"{p.from_} -> {p.to}", "onset": clock(p.t)}
        if d["decision"] == "confirmed":
            panels = tb.shape_panels(c, ctx.first)
            for key, p in zip(("before", "after"), panels, strict=True):
                if p["low_visibility"]:
                    continue
                win = re.search(r"\d{1,3}:\d{2}-\d{1,3}:\d{2}", p["caption"])
                e[key] = _shape_numbers(tb, c.team, p["label"], p["frames"],
                                        p.get("own_box_share"), win.group(0) if win else "")
            a = (alerts or {}).get(c.id)
            if a is not None:
                e["alert"] = {"id": a.alert_id, "status": a.status,
                              "evidence_image": a.evidence_image}
        events.append(e)
    lo, hi = ctx.footage
    match = {"id": ctx.match.match_id, "teams": names, "footage": f"{clock(lo)}-{clock(hi)}",
             "view": ctx.view, "unavailable": tb.unavailable()}
    if note:
        match["note"] = note
    return {"match": match, "segments": segs, "events": events, "not_verified": not_verified}


# --------------------------------------------------------------------------- check


def _segment_items(inp: dict[str, Any], cite: str) -> list[dict[str, Any]] | None:
    """The segment(s) a `seg a-b` citation covers: one segment, or a run of consecutive ones
    that starts at a segment start and ends at a segment end."""
    a, b = cite.removeprefix("seg ").split("-")
    segs = inp["segments"]
    starts = [s["seg"].split("-")[0] for s in segs]
    ends = [s["seg"].split("-")[1] for s in segs]
    if a not in starts or b not in ends:
        return None
    i, j = starts.index(a), ends.index(b)
    return segs[i:j + 1] if i <= j else None


def _sentences(text: str) -> list[str]:
    parts = [p for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p]
    out: list[str] = []
    for p in parts:  # a citation left after the full stop belongs to the sentence before
        if out and not re.sub(CITE_RE, "", p).strip(" .;,"):
            out[-1] += " " + p
        else:
            out.append(p)
    return out


def report_texts(rep: dict[str, Any]) -> list[tuple[str, str]]:
    """(section, text) of every string in a report."""
    out = [("formation_story", s) for s in rep.get("formation_story", [])]
    for c in rep.get("changes", []):
        out += [("changes", c.get("what_changed", "")), ("changes", c.get("may_have_fixed", ""))]
    for k in ("not_alerted", "recommendations", "limits"):
        out += [(k, s) for s in rep.get(k, [])]
    return out


def check_report(rep: Any, inp: dict[str, Any], cfg: dict[str, Any]) -> list[str]:
    """Citation and number checks (module docstring); empty list = acceptable."""
    if not isinstance(rep, dict):
        return ["not a JSON object"]
    probs: list[str] = []
    for k in ("formation_story", "changes", "not_alerted", "recommendations", "limits"):
        if not isinstance(rep.get(k), list):
            probs.append(f"'{k}' missing or not a list")
    if probs:
        return probs
    if len(rep["recommendations"]) != 3:
        probs.append(f"{len(rep['recommendations'])} recommendations, not 3")
    events = {e["id"]: e for e in inp["events"]}
    confirmed = {i for i, e in events.items() if e["decision"] == "confirmed"}
    got = {c.get("event") for c in rep["changes"] if isinstance(c, dict)}
    if got != confirmed:
        probs.append(f"changes cover {sorted(x for x in got if x)}, confirmed are "
                     f"{sorted(confirmed)}")
    slack = float(cfg["presentation"]["explain"]["time_slack_s"])
    story = " ".join(x for x in rep["formation_story"] if isinstance(x, str))
    for t in inp["match"]["teams"].values():
        if t not in story:
            probs.append(f"formation_story: says nothing about {t}")
    grounded = [("may_have_fixed", c.get("may_have_fixed", "")) for c in rep["changes"]
                if isinstance(c, dict)] + [("recommendations", r)
                                           for r in rep["recommendations"]]
    for section, text in grounded:  # claims rest on data: a cited number or time each
        if isinstance(text, str) and not (CITE_RE.search(text) and (
                _scan(CITE_RE.sub(" ", text))[0] or _scan(CITE_RE.sub(" ", text))[1])):
            probs.append(f"{section}: no cited number or time in '{text[:60]}'")
    for section, text in report_texts(rep):
        if not isinstance(text, str) or not text.strip():
            probs.append(f"{section}: empty text")
            continue
        m = _UNAVAILABLE.search(text)
        if m:
            probs.append(f"{section}: mentions unavailable data '{m.group(0)}'")
        for tok in re.findall(r"\[([^\]]*)\]", text):
            if not CITE_RE.fullmatch(f"[{tok}]"):
                probs.append(f"{section}: [{tok}] is not a source")
        for s in _sentences(text):
            cites = CITE_RE.findall(s)
            items: list[Any] = []
            for c in cites:
                if c.startswith("evt_"):
                    if c in events:
                        items.append(events[c])
                    else:
                        probs.append(f"{section}: cites {c}, which is not a decided event")
                else:
                    seg = _segment_items(inp, c)
                    if seg is None:
                        probs.append(f"{section}: cites [{c}], which is not a segment run")
                    else:
                        items += seg
            nums, clocks = _scan(CITE_RE.sub(" ", s))
            if not (nums or clocks):
                continue
            if not cites:
                probs.append(f"{section}: no citation for '{s[:70]}'")
                continue
            ok: Allowed = allowed_numbers({"items": items})
            for x, dec, _unit in nums:
                if not _matches(x, dec, ok.by_unit.get("any", set())):
                    probs.append(f"{section}: {x:g} is not in the cited items ('{s[:50]}')")
            for t in clocks:
                if not any(abs(t - c) <= slack for c in ok.clocks):
                    probs.append(f"{section}: clock {t // 60}:{t % 60:02d} is not in the cited "
                                 "items")
    return probs


# --------------------------------------------------------------------------- template


def _join(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _runs(inp: dict[str, Any], team: str) -> list[tuple[str, str, str]]:
    """(formation, start, end) runs of a team's segment formations."""
    runs: list[list[str]] = []
    for s in inp["segments"]:
        a, b = s["seg"].split("-")
        f = s[team]["formation"]
        if runs and runs[-1][0] == f:
            runs[-1][2] = b
        else:
            runs.append([f, a, b])
    return [(f, a, b) for f, a, b in runs]


def template_report(inp: dict[str, Any]) -> dict[str, Any]:
    """The report written by code from the inputs (always passes `check_report`)."""
    teams = inp["match"]["teams"]
    story = []
    for side in ("home", "away"):
        t = teams[side]
        runs = [f"{'no settled shape' if f == UNCERTAIN else f} {a}-{b} [seg {a}-{b}]"
                for f, a, b in _runs(inp, t)]
        story.append(f"{t}, first-pass reading: {_join(runs)}.")
    confirmed = [e for e in inp["events"] if e["decision"] == "confirmed"]
    others = [e for e in inp["events"] if e["decision"] != "confirmed"]
    if confirmed:
        story.append("Checked by the agent and confirmed: " + _join(
            [f"{e['team']} {e['change']} at {e['onset']} [{e['id']}]" for e in confirmed]) + ".")
    changes = []
    for e in confirmed:
        b, a = e.get("before"), e.get("after")
        what = (f"{e['team']} went from {e['change'].replace(' -> ', ' to ')} at {e['onset']} "
                f"({e['lines']}), and the new shape held: {e['reason']} [{e['id']}].")
        fixes: list[str] = []
        if b and a:
            what += (f" Typical before ({b['window']}): line {b['line_m']} m from its goal, "
                     f"{b['width_m']} m wide; after ({a['window']}): line {a['line_m']} m, "
                     f"{a['width_m']} m wide [{e['id']}].")
            if a["width_m"] is not None and b["width_m"] is not None \
                    and a["width_m"] - b["width_m"] >= 8:
                fixes.append(f"spread the team wider ({b['width_m']} m to {a['width_m']} m) "
                             f"[{e['id']}]")
        deep = _deep_before(inp, e)
        if deep is not None:
            fixes.append(f"get out of a spell deep in its own half (line {deep[1]} m from its "
                         f"goal in {deep[0]}) [seg {deep[0]}]")
        old, new = (parse_formation(x) for x in e["change"].split(" -> "))
        if new[-1] > old[-1]:
            fixes.append(f"put an extra player up front ({e['lines']}) [{e['id']}]")
        if not fixes:
            fixes.append(f"change its shape at {e['onset']} for a reason the shape data "
                         f"cannot show [{e['id']}]")
        changes.append({"event": e["id"], "what_changed": what,
                        "may_have_fixed": f"{e['team']} may have been trying to "
                                          f"{_join(fixes)}. This is read from the shape alone: "
                                          "there is no event data to confirm the intention."})
    not_alerted = []
    for e in others:
        s = f"{e['team']} {e['change']} at {e['onset']} was {e['decision']}: {e['reason']}"
        held = e.get("new_shape_pct")
        if e.get("undoes") and held is not None and held >= 60:
            s += (f"; the second look still saw the new shape in {held}% of readings, so this "
                  "may be a real change the return-leg rule misses")
        not_alerted.append(s + f" [{e['id']}].")
    if inp["not_verified"]:
        not_alerted.append("The agent did not check the other candidates of this window "
                           f"({', '.join(x['id'] for x in inp['not_verified'])}): they are "
                           "first-pass readings, not findings.")
    recs = _template_recs(inp, confirmed, others)
    limits = ["Shapes are read from player positions only: with no event data, the intentions "
              "above are guesses, and changes the agent did not check are not findings."]
    if inp["match"].get("note"):
        limits.append(inp["match"]["note"])
    return {"formation_story": story, "changes": changes, "not_alerted": not_alerted,
            "recommendations": recs, "limits": limits}


def _deep_before(inp: dict[str, Any], e: dict[str, Any]) -> tuple[str, float] | None:
    """The segment just before a change if the team's line sat within 15 m of its goal."""
    for s in inp["segments"]:
        a, b = s["seg"].split("-")
        if b == e["onset"]:
            line = s[e["team"]]["line_m"]
            if line is not None and line < 15.0:
                return s["seg"], line
    return None


_WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}


def _template_recs(inp: dict[str, Any], confirmed: list[dict[str, Any]],
                   others: list[dict[str, Any]]) -> list[str]:
    recs: list[str] = []
    for e in confirmed:
        old, new = (parse_formation(x) for x in e["change"].split(" -> "))
        back = _WORDS.get(new[0], str(new[0]))
        if new[0] < old[0]:
            recs.append(f"Against {e['team']}'s back {back} (from {e['onset']} [{e['id']}]), "
                        "attack the channels behind the wing-backs and pull the outside "
                        "centre-backs wide.")
        elif new[0] > old[0]:
            recs.append(f"Against {e['team']}'s back {back} (from {e['onset']} [{e['id']}]), "
                        "use the extra space in midfield: one more of their players is "
                        "defending.")
        deep = _deep_before(inp, e)
        if deep is not None:
            recs.append(f"With {e['team']}, practise stepping out of a deep block together: the "
                        f"line sat {deep[1]} m from goal in {deep[0]} [seg {deep[0]}].")
    for e in others:
        held = e.get("new_shape_pct")
        if e.get("undoes") and held is not None and held >= 60:
            recs.append(f"Review {e['onset']} on video: {e['team']}'s {e['change'].split()[-1]} "
                        f"showed in {held}% of second-look readings but was not alerted "
                        f"[{e['id']}].")
    for e in confirmed:
        recs.append(f"Check the evidence image of the {e['onset']} change before acting on it "
                    f"[{e['id']}].")
    spells = sorted(((_secs(b) - _secs(a), t, f, a, b) for t in inp["match"]["teams"].values()
                     for f, a, b in _runs(inp, t) if f != UNCERTAIN), reverse=True)
    for _, t, f, a, b in spells[:2]:
        recs.append(f"Study {t}'s {f} in {a}-{b}, its longest spell in one shape, to prepare "
                    f"for it [seg {a}-{b}].")
    return recs[:3]


def _secs(c: str) -> int:
    m, s = c.split(":")
    return int(m) * 60 + int(s)


# --------------------------------------------------------------------------- markdown


def render_markdown(rep: dict[str, Any], inp: dict[str, Any], source: str) -> str:
    m, teams = inp["match"], inp["match"]["teams"]
    events = {e["id"]: e for e in inp["events"]}
    out = [f"# Coach report: {teams['home']} vs {teams['away']}, {m['footage']}", "",
           f"*Match `{m['id']}`, {m['view']} camera, Gaffer pipeline (OpenCV 5) + agent "
           f"checks. Not available: {', '.join(m['unavailable']) or 'nothing'}. Written by: "
           f"{source}. Sources: [evt_…] = a decision of the agent, [seg a-b] = the tactics "
           "timeline (first pass).*", "", "## Formation story", ""]
    out += [f"- {s}" for s in rep["formation_story"]]
    out += ["", "## Confirmed changes", ""]
    if not rep["changes"]:
        out.append("- None in this footage.")
    for c in rep["changes"]:
        e = events.get(c["event"], {})
        out += [f"### {e.get('team')} {e.get('change')} at {e.get('onset')} ({c['event']})", "",
                f"- **What changed:** {c['what_changed']}",
                f"- **What it may have been trying to fix:** {c['may_have_fixed']}"]
        if e.get("alert"):
            a = e["alert"]
            out.append(f"- **Alert:** `{a['id']}` ({a['status']}, waits for the coach); "
                       f"evidence `{a['evidence_image']}`")
        out.append("")
    out += ["## Not alerted", ""] + [f"- {s}" for s in rep["not_alerted"]]
    out += ["", "## Three recommendations", ""]
    out += [f"{i}. {s}" for i, s in enumerate(rep["recommendations"], 1)]
    out += ["", "## Limits", ""] + [f"- {s}" for s in rep["limits"]] + [""]
    return "\n".join(out)


# --------------------------------------------------------------------------- LLM


def _parse_json(text: str) -> Any:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


class Reporter:
    """One LLM call (one retry after a failed check), else the template."""

    def __init__(self, cfg: dict[str, Any], llm: Any | None = None,
                 max_cost_usd: float | None = None) -> None:
        self.cfg, self.llm = cfg, llm
        self.p = cfg["presentation"]["report"]
        self.model = cfg["bedrock"]["model_id"]
        self.prices = cfg["agent"]["llm"]["prices_per_1k"]
        self.max_cost = float(max_cost_usd if max_cost_usd is not None
                              else self.p["max_cost_usd"])
        self.calls, self.cost, self.log = 0, 0.0, []

    def _call(self, msgs: list[dict[str, Any]]) -> str:
        pin, pout = self.prices.get(self.model, (0.0, 0.0))
        if self.cost + 6000 / 1000 * float(pin) + int(self.p["max_tokens"]) / 1000 * \
                float(pout) > self.max_cost:
            raise BedrockError("report budget spent")
        r = self.llm.chat(msgs, system=REPORT_SYSTEM, model_id=self.model,
                          max_tokens=int(self.p["max_tokens"]),
                          temperature=float(self.p["temperature"]), purpose="coach_report")
        tin, tout = int(r.usage.get("input_tokens", 0)), int(r.usage.get("output_tokens", 0))
        self.calls += 1
        self.cost += tin / 1000 * float(pin) + tout / 1000 * float(pout)
        self.log.append({"in": tin, "out": tout, "latency_ms": round(r.latency_ms)})
        return r.text

    def generate(self, inp: dict[str, Any]) -> dict[str, Any]:
        """{report, source ("Nova 2 Lite (checked)" | "code template"), attempts}."""
        attempts: list[dict[str, Any]] = []
        if self.llm is not None:
            msgs = [user_message("DATA:\n" + json.dumps(inp, separators=(",", ":")))]
            for _ in range(1 + int(self.p["retries"])):
                try:
                    text = self._call(msgs)
                except BedrockError as exc:
                    attempts.append({"error": str(exc).splitlines()[0]})
                    break
                rep = _parse_json(text)
                probs = check_report(rep, inp, self.cfg)
                attempts.append({"problems": probs, "raw": text})
                if not probs:
                    return {"report": rep, "source": "Nova 2 Lite (checked)",
                            "attempts": attempts}
                msgs += [{"role": "assistant", "content": [{"text": text}]},
                         user_message("The report failed these checks:\n- " + "\n- ".join(
                             probs[:12]) + "\nReturn the corrected JSON object only.")]
        rep = template_report(inp)
        return {"report": rep, "source": "code template", "attempts": attempts,
                "template_problems": check_report(rep, inp, self.cfg)}


# --------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser(description="Gaffer coach report for one match")
    ap.add_argument("--match", required=True, help="match_state JSON")
    ap.add_argument("--view", default=None)
    ap.add_argument("--decided", required=True,
                    help="decided events: scripts/explain_real.py explanations.json")
    ap.add_argument("--set", default=None, help="set name inside --decided (e.g. w900)")
    ap.add_argument("--alerts", default=None, help="alerts.jsonl with the confirmed alerts")
    ap.add_argument("--out", required=True, help="output path without suffix (.md + .json)")
    ap.add_argument("--no-llm", action="store_true", help="template only (no Bedrock call)")
    ap.add_argument("--max-cost-usd", type=float, default=None)
    ap.add_argument("--note", default=None, help="where the footage comes from (no numbers)")
    args = ap.parse_args(argv)
    try:
        ctx = MatchContext(load_match_state(repo_path(args.match)), cfg, view=args.view)
    except ContractError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    data = json.loads(repo_path(args.decided).read_text(encoding="utf-8"))
    rows = [x for x in data.get("candidates", data) if args.set is None or x["set"] == args.set]
    decided = []
    for x in rows:
        d = x.get("facts", {}).get("results", {}).get(x.get("facts", {}).get("decisive", ""), {})
        decided.append({"event_id": x["event_id"], "decision": x["decision"],
                        "reason": x.get("reason_now") or x["reason"],
                        "explanation": x.get("after") or x.get("explanation"),
                        "new_shape_pct": d.get("new_shape_pct"),
                        "clear_readings_after": d.get("clear_readings_after"),
                        "fps": d.get("fps")})
    alerts = None
    if args.alerts:
        alerts = {a.event_id: a for a in AlertStore(args.alerts).all().values()}
    inp = build_inputs(ctx, decided, alerts, args.note)
    llm = None
    if not args.no_llm:
        from gaffer.llm.bedrock_client import BedrockClient

        try:
            llm = BedrockClient(cfg)
        except BedrockError as exc:
            print(f"WARNING: {exc}; using the template", file=sys.stderr)
    t0 = time.perf_counter()
    rep = Reporter(cfg, llm, args.max_cost_usd)
    res = rep.generate(inp)
    md = render_markdown(res["report"], inp, res["source"])
    out = repo_path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    Path(f"{out}.md").write_text(md, encoding="utf-8")
    Path(f"{out}.json").write_text(json.dumps(
        {"inputs": inp, **res, "llm": {"calls": rep.calls, "cost_usd": round(rep.cost, 5),
                                       "log": rep.log},
         "wall_s": round(time.perf_counter() - t0, 1)}, indent=2, default=str),
        encoding="utf-8")
    print(md)
    print(f"source: {res['source']} | attempts: "
          f"{[len(a.get('problems', [])) if 'problems' in a else a for a in res['attempts']]}"
          f" | LLM calls {rep.calls}, ${rep.cost:.4f} | -> {out}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
