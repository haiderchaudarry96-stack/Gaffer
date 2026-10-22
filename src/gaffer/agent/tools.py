"""The agent's tools (docs/AGENT_DESIGN.md §2): schemas, execution, per-candidate state.

Ten tools: five data tools, three vision tools, `record_decision` and `propose_alert`.
Arguments are validated with pydantic models; the JSON schema Bedrock receives is generated
from the same models (`TOOL_SPECS`), so the two cannot drift. Every result is a small dict
(<= 1 KB, tested) carrying a `ref` (`R1`, `R2`, ... per candidate) used for citations; times
come with a `clock` string so the model never converts units itself.

Protocol and grounding checks are tool preconditions and return `{"error": "not_allowed"}`:
`render_evidence` / `propose_alert` only after `record_decision(confirmed)`, decisions only
within what the rules verdict allows (`verify.allowed_decisions`), citations must exist and
cited times / `mm:ss` clocks must fall inside a cited tool's window (+-5 s).

Vision backends: `synthetic` / `annotation` (no video: quality from the MatchState, re-analysis
= tactics engine on a slice at the MatchState rate, minimaps only) and `video` (OpenCV 5 on the
source video via `agent/vision.py`: camera checks, perception re-run with budget + cache, an
evidence frame with the shape projected back into the image).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from gaffer.agent.alerts import AlertError, AlertStore, compose_explanation
from gaffer.agent.context import MatchContext, PassData
from gaffer.agent.verify import (
    Candidate,
    Decision,
    Geometry,
    PassEvidence,
    VerdictResult,
    allowed_decisions,
    decision_reason,
    evaluate,
)
from gaffer.agent.vision import (
    OverBudget,
    VideoBackend,
    VisionConfig,
    VisionError,
    problems_of,
    snap,
    write_image,
)
from gaffer.config import repo_path
from gaffer.perception.pitch import Markings, PitchModel
from gaffer.tactics.formation import UNCERTAIN, WindowResult, build_template, fit_template
from gaffer.tactics.metrics import possession_share, span_metrics

CLOCK_RE = re.compile(r"\b(\d{1,3}):([0-5]\d)\b")
REF_RE = re.compile(r"\[(R\d+)\]")
TIME_SLACK_S = 5.0
MAX_STRIP = 18  # labels in a re-analysis strip


def clock(t: float) -> str:
    """Match seconds -> 'mm:ss' (minutes may exceed 59)."""
    t = max(0.0, float(t))
    return f"{int(t // 60)}:{int(round(t % 60)) % 60:02d}"


def _r(v: float | None, n: int = 2) -> float | None:
    return None if v is None else round(float(v), n)


# --------------------------------------------------------------------------- argument models


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


Team = Literal["home", "away"]
EVENT_ID = r"^evt_\d{3}$"


class MatchOverviewArgs(_Args):
    pass


class FormationAtArgs(_Args):
    team: Team
    t: float = Field(ge=0)


class ListCandidatesArgs(_Args):
    team: Team | None = None
    from_s: float | None = Field(default=None, ge=0)
    to_s: float | None = Field(default=None, ge=0)
    status: Literal["candidate", "confirmed", "rejected", "uncertain"] | None = None


class MetricsArgs(_Args):
    team: Team
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)


class CompareWindowsArgs(_Args):
    team: Team
    a_start: float = Field(ge=0)
    a_end: float = Field(ge=0)
    b_start: float = Field(ge=0)
    b_end: float = Field(ge=0)


class QualityArgs(_Args):
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)
    why: str = Field(max_length=120)


class ReanalyseArgs(_Args):
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)
    sample_fps: Literal[4, 6]
    event_id: str | None = Field(default=None, pattern=EVENT_ID)
    why: str = Field(max_length=120)


class RenderArgs(_Args):
    event_id: str = Field(pattern=EVENT_ID)
    why: str = Field(max_length=120)


class Citation(_Args):
    ref: str = Field(pattern=r"^R\d+$")
    t: float | None = None


class DecisionArgs(_Args):
    event_id: str = Field(pattern=EVENT_ID)
    decision: Literal["confirmed", "rejected", "uncertain"]
    reason: str = Field(max_length=200)
    citations: list[Citation] = Field(min_length=1, max_length=5)


class AlertArgs(_Args):
    event_id: str = Field(pattern=EVENT_ID)
    title: str = Field(max_length=80)
    explanation: str = Field(max_length=280)
    suggestion: str = Field(max_length=160)


TOOLS: dict[str, tuple[type[_Args], str]] = {
    "get_match_overview": (MatchOverviewArgs,
                           "Match source, camera view and trust, footage span, candidate count, "
                           "and what is unavailable (e.g. ball, possession)."),
    "get_formation_at": (FormationAtArgs,
                         "Formation label of one team for the 30 s window ending at t, "
                         "with its timeline segment."),
    "list_candidate_changes": (ListCandidatesArgs,
                               "Candidate shape changes (max 10, by time), optionally filtered "
                               "by team, time span and status."),
    "get_metrics": (MetricsArgs,
                    "Shape metrics of one team over a window (<= 600 s): defensive line, "
                    "width, compactness, coverage."),
    "compare_windows": (CompareWindowsArgs,
                        "Formation shares and metrics of one team in two windows (a = before, "
                        "b = after)."),
    "check_frame_quality": (QualityArgs,
                            "Vision check of a window: homography, camera motion/zoom/cuts, "
                            "share of frames with enough players per team."),
    "reanalyse_window": (ReanalyseArgs,
                         "Second look: re-run perception + tactics on a window at a higher "
                         "rate. Give event_id to compare with that candidate."),
    "render_evidence": (RenderArgs,
                        "Render the evidence image for a CONFIRMED candidate (needed before "
                        "propose_alert)."),
    "record_decision": (DecisionArgs,
                        "Record confirmed / rejected / uncertain for the candidate, with a "
                        "short reason and 1-5 citations of tool results [ref]."),
    "propose_alert": (AlertArgs,
                      "Create a pending coach alert for a confirmed candidate with rendered "
                      "evidence. The explanation must cite at least one [Rn]."),
}
VISION_TOOLS = {"check_frame_quality", "reanalyse_window", "render_evidence"}


def _clean_schema(node: Any, defs: dict[str, Any] | None = None) -> Any:
    """Pydantic JSON schema -> the plain subset Bedrock tools use: refs inlined, titles and
    null branches removed (optional = not required)."""
    if isinstance(node, dict):
        if defs is None:
            defs = node.get("$defs", {})
        if "$ref" in node:
            return _clean_schema(defs[node["$ref"].split("/")[-1]], defs)
        if "anyOf" in node:
            branches = [b for b in node["anyOf"] if b.get("type") != "null"]
            if len(branches) == 1:
                merged = {**{k: v for k, v in node.items() if k not in ("anyOf", "default")},
                          **branches[0]}
                return _clean_schema(merged, defs)
        out = {}
        for k, v in node.items():
            if k in ("title", "$defs") or (k == "default" and v is None):
                continue  # schema keywords only: property *names* are handled below
            if k == "properties" and isinstance(v, dict):
                out[k] = {name: _clean_schema(sub, defs) for name, sub in v.items()}
                continue
            out[k] = _clean_schema(v, defs)
        if out.get("type") == "object" and "properties" in out:
            out["additionalProperties"] = False
        return out
    if isinstance(node, list):
        return [_clean_schema(v, defs) for v in node]
    return node


def tool_schema(name: str) -> dict[str, Any]:
    schema = _clean_schema(TOOLS[name][0].model_json_schema())
    schema.setdefault("properties", {})
    schema["type"] = "object"
    schema["additionalProperties"] = False
    return schema


def tool_specs() -> list[dict[str, Any]]:
    """Converse `toolConfig.tools` entries for all ten tools."""
    return [{"toolSpec": {"name": n, "description": d, "inputSchema": {"json": tool_schema(n)}}}
            for n, (_, d) in TOOLS.items()]


# --------------------------------------------------------------------------- state


@dataclass
class RefInfo:
    tool: str
    window: tuple[float, float] | None
    ok: bool


@dataclass
class CandidateState:
    """What the agent knows and has done for one candidate."""

    cand: Candidate
    first: PassEvidence
    latest: PassEvidence
    verdict: VerdictResult
    refs: dict[str, RefInfo] = field(default_factory=dict)
    geometry: Geometry | None = None
    second_look: bool = False
    looked: bool = False  # a vision tool (quality check / re-analysis) has run successfully
    data: PassData | None = None  # the re-analysed pass that covers the required span
    quality: dict[str, Any] | None = None  # last check_frame_quality summary (for reports)
    reanalysis: dict[str, Any] | None = None  # last reanalyse_window summary (for reports)
    decision: Decision | None = None
    reason: str = ""  # code-written (verify.decision_reason): the primary reason everywhere
    decision_text: str = ""  # the `reason` text of the record_decision call (trace only)
    explanation: str = ""  # coach-facing, from agent/explain.py: checked model text or template
    explanation_source: str = ""  # "agent" | "template"
    explanation_flags: list[str] = field(default_factory=list)  # why a model text was replaced
    results: dict[str, dict[str, Any]] = field(default_factory=dict)  # result summary per ref
    verdict_ref: str = "R0"  # ref of the last result that updated the verdict
    citations: list[dict[str, Any]] = field(default_factory=list)
    evidence_image: str | None = None
    alert_id: str | None = None
    vision_calls: int = 0
    reanalyses: int = 0
    tool_calls: list[str] = field(default_factory=list)
    exhausted: bool = False  # no more evidence can be gathered (budget / steps)

    @property
    def done(self) -> bool:
        return self.decision in ("rejected", "uncertain") or self.alert_id is not None

    def next_ref(self) -> str:
        return f"R{len(self.refs)}"  # R0 is the candidate card


# --------------------------------------------------------------------------- toolbox


class Toolbox:
    """Executes tools for one match. `run` never raises for a model error: it returns an
    error result the model can read."""

    def __init__(self, ctx: MatchContext, store: AlertStore | None = None,
                 evidence_dir: str | Path | None = None,
                 video: VideoBackend | None = None) -> None:
        self.ctx = ctx
        self.cfg = ctx.cfg["agent"]
        self.store = store or AlertStore()
        self.evidence_dir = repo_path(evidence_dir or self.cfg["outputs"]["evidence_dir"])
        self.statuses: dict[str, str] = {c.id: "candidate" for c in ctx.candidates}
        self.video = video  # OpenCV on the source video (backend "video")

    def reanalysis_fps(self) -> list[int]:
        """Allowed re-analysis rates for this camera view (config `agent.views`)."""
        views = self.cfg["views"]
        return sorted(int(f) for f in views.get(self.ctx.view or "top",
                                                views["top"])["reanalysis_fps"])

    def _need_video(self) -> VideoBackend:
        if self.video is None:
            raise _ToolFailure("no_video", "this match has no video backend configured",
                               {"retryable": False})
        return self.video

    # ---------------------------------------------------------------- state
    def new_state(self, cand: Candidate) -> CandidateState:
        first = self.ctx.evidence(cand)
        st = CandidateState(cand=cand, first=first, latest=first,
                            verdict=VerdictResult("need_more", [], [], ""))
        st.refs["R0"] = RefInfo("candidate_card", self.card_window(cand), True)
        self._update_verdict(st)
        return st

    def card_window(self, cand: Candidate) -> tuple[float, float]:
        v = self.ctx.vcfg
        return cand.t - v.before_s, cand.detected_at_s + v.lookahead_s

    def _update_verdict(self, st: CandidateState) -> None:
        st.verdict = evaluate(st.latest, self.ctx.vcfg, backend=self.ctx.backend,
                              view=self.ctx.view, geometry=st.geometry,
                              second_look=st.second_look)

    def rules_block(self, st: CandidateState) -> dict[str, Any]:
        return {**st.verdict.as_dict(), "next_step": self.next_step(st)}

    def next_step(self, st: CandidateState) -> str:
        """What the protocol expects next (spike 15 Oct: 5 of 6 confirmations called
        render_evidence before record_decision and were blocked)."""
        if st.decision == "confirmed":
            return ("render_evidence" if st.evidence_image is None else
                    f"propose_alert, citing [{st.verdict_ref}] in the explanation")
        if st.decision is not None:
            return "done"
        v = st.verdict
        a, b = self.ctx.required_span(st.cand)
        if v.verdict == "confirm" and not st.looked:
            return (f"check_frame_quality over [{a:.0f}, {b:.0f}] (a confirmation needs a "
                    "vision check)")
        left = st.reanalyses < int(self.cfg["limits"]["max_reanalyses_per_candidate"])
        if v.verdict == "need_more":
            if "quality_check" in v.missing:
                return f"check_frame_quality over [{a:.0f}, {b:.0f}]"
            if not st.second_look and left and not st.exhausted:
                return f"reanalyse_window over [{a:.0f}, {b:.0f}] with event_id {st.cand.id}"
            if self.ctx.backend == "video" and left and not st.exhausted:
                return "reanalyse_window at a higher sample_fps, or record_decision(uncertain)"
            return "record_decision(uncertain): no more evidence can be gathered"
        allowed = " or ".join(allowed_decisions(v.verdict))
        if v.verdict == "confirm":
            return f"record_decision({allowed}) now; render_evidence only after it"
        return f"record_decision({allowed}) now"

    def card(self, st: CandidateState) -> str:
        """The first user message for a candidate (built by code: no LLM call)."""
        c, ctx = st.cand, self.ctx
        a, b = ctx.required_span(c)
        same = [o for o in ctx.candidates if o.team == c.team and o.id != c.id
                and abs(o.t - c.t) <= 120]
        other = [o for o in ctx.candidates if o.team != c.team and abs(o.t - c.t) <= 30]
        trust = ctx.vcfg.views.get(ctx.view or "", {}).get("camera_trust", "n/a")
        unavailable = ", ".join(self.unavailable()) or "nothing"
        lines = [
            f"Candidate {c.id} | match {ctx.match.match_id} | source {ctx.match.source} | "
            f"backend {ctx.backend} | view {ctx.view or 'n/a'} (camera trust: {trust})",
            f"{c.team} ({self.team_name(c.team)}), onset {c.t:.1f} s ({clock(c.t)}), "
            f"detected {c.detected_at_s:.1f} s ({clock(c.detected_at_s)}), "
            f"{c.from_} -> {c.to}, engine confidence {c.confidence:.2f}",
            f'engine evidence [R0]: "{c.evidence}"',
            "same team within 120 s: " + ("; ".join(
                f"{o.id} {o.t:.0f} s {o.from_} -> {o.to}" for o in same) or "none"),
            "other team within 30 s: " + ("; ".join(
                f"{o.id} {o.t:.0f} s {o.from_} -> {o.to}" for o in other) or "none"),
            f"footage {ctx.footage[0]:.0f}-{ctx.footage[1]:.0f} s; unavailable: {unavailable}",
            f"rules: verdict {st.verdict.verdict}, failed {st.verdict.failed}, missing "
            f"{st.verdict.missing}; required re-analysis span [{a:.0f}, {b:.0f}]",
            f"next step: {self.next_step(st)}",
        ]
        return "\n".join(lines)

    def team_name(self, team: str) -> str:
        return getattr(self.ctx.match.teams, team).name

    def unavailable(self) -> list[str]:
        frames = self.ctx.match.frames
        ball = any(f.ball is not None and f.ball.visible for f in frames)
        poss = any(f.possession in ("home", "away") for f in frames)
        out = [] if ball else ["ball"]
        if not poss:
            out += ["possession", "pressing"]
        return out

    # ---------------------------------------------------------------- dispatch
    def run(self, st: CandidateState, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Validate and execute one tool call; returns the result with its `ref`."""
        ref = st.next_ref()
        if name not in TOOLS:
            return self._err(st, ref, name, None, "unknown_tool",
                             f"no tool named {name!r}; tools: {', '.join(TOOLS)}")
        try:
            parsed = TOOLS[name][0].model_validate(args or {})
        except ValidationError as exc:
            msg = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'args'}: {e['msg']}"
                            for e in exc.errors()[:4])
            return self._err(st, ref, name, None, "invalid_args", msg)
        st.tool_calls.append(name)
        if name in VISION_TOOLS:
            st.vision_calls += 1
        try:
            result, window = getattr(self, f"_t_{name}")(st, parsed)
        except _NotAllowed as exc:
            return self._err(st, ref, name, None, "not_allowed", str(exc))
        except _ToolFailure as exc:
            return self._err(st, ref, name, None, exc.code, str(exc), exc.extra)
        st.refs[ref] = RefInfo(name, window, True)
        st.results[ref] = {k: v for k, v in result.items()
                           if k not in ("rules", "labels", "candidates_in_window")}
        if name in ("check_frame_quality", "reanalyse_window"):
            st.verdict_ref = ref
        return {"ref": ref, **result}

    def reject(self, st: CandidateState, name: str, msg: str) -> dict[str, Any]:
        """A refused call (loop guard): gets a ref, never runs."""
        return self._err(st, st.next_ref(), name, None, "not_allowed", msg)

    def _err(self, st: CandidateState, ref: str, name: str, window: Any, code: str, msg: str,
             extra: dict[str, Any] | None = None) -> dict[str, Any]:
        st.refs[ref] = RefInfo(name, window, False)
        st.results[ref] = {"error": code, "message": msg[:300], **(extra or {})}
        return {"ref": ref, "error": code, "message": msg[:300], **(extra or {})}

    def _window(self, a: float, b: float, max_s: float | None = None) -> tuple[float, float]:
        if b <= a:
            raise _ToolFailure("invalid_window", f"end ({b}) must be after start ({a})")
        lim = max_s or float(self.cfg["vision"]["max_window_s"])
        if b - a > lim:
            raise _ToolFailure("window_too_long", f"window {b - a:.0f} s > {lim:.0f} s")
        lo, hi = self.ctx.footage
        if b < lo or a > hi:
            raise _ToolFailure("outside_footage", f"footage covers {lo:.0f}-{hi:.0f} s")
        return max(a, lo), min(b, hi)

    # ---------------------------------------------------------------- data tools
    def _t_get_match_overview(self, st: CandidateState, a: MatchOverviewArgs):
        ctx = self.ctx
        q = ctx.result.timeline.quality
        return {"match_id": ctx.match.match_id, "source": ctx.match.source,
                "backend": ctx.backend, "view": ctx.view,
                "camera_trust": ctx.vcfg.views.get(ctx.view or "", {}).get("camera_trust", "n/a"),
                "footage_s": [round(ctx.footage[0], 1), round(ctx.footage[1], 1)],
                "teams": {"home": ctx.match.teams.home.name, "away": ctx.match.teams.away.name},
                "candidates": len(ctx.candidates), "uncertain_fraction": q.uncertain_fraction,
                "unavailable": self.unavailable(), "warnings": q.warnings[:3]}, ctx.footage

    def _t_get_formation_at(self, st: CandidateState, a: FormationAtArgs):
        ws = [w for w in self.ctx.first.windows[a.team] if w.t <= a.t + 1e-6]
        if not ws:
            raise _ToolFailure("no_window", f"no formation window ends before {a.t:.0f} s")
        w = ws[-1]
        seg = next((s for s in self.ctx.result.timeline.segments
                    if s.start_s <= w.t < s.end_s), None)
        out = {"team": a.team, "t": round(w.t, 1), "clock": clock(w.t), "label": w.label,
               "confidence": _r(w.confidence), "visible_mean": _r(w.mean_visible, 1)}
        if seg is not None:
            out["segment"] = {"start_s": seg.start_s, "end_s": seg.end_s,
                              "formation": getattr(seg, a.team).formation}
        return out, (w.t - w.window_s, w.t)

    def _t_list_candidate_changes(self, st: CandidateState, a: ListCandidatesArgs):
        sel = [c for c in self.ctx.candidates
               if (a.team is None or c.team == a.team)
               and (a.from_s is None or c.t >= a.from_s) and (a.to_s is None or c.t <= a.to_s)
               and (a.status is None or self.statuses[c.id] == a.status)]
        lo, hi = self.ctx.footage
        return {"total": len(sel), "returned": min(10, len(sel)), "candidates": [
            {"id": c.id, "t": round(c.t, 1), "clock": clock(c.t), "team": c.team,
             "from": c.from_, "to": c.to, "conf": _r(c.confidence),
             "status": self.statuses[c.id]} for c in sel[:10]]}, \
            (a.from_s if a.from_s is not None else lo, a.to_s if a.to_s is not None else hi)

    def _t_get_metrics(self, st: CandidateState, a: MetricsArgs):
        lo, hi = self._window(a.start_s, a.end_s)
        frames = [f for f in self.ctx.first.frames[a.team] if lo <= f.t <= hi]
        m = span_metrics(frames, a.team, self.ctx.tcfg)
        out: dict[str, Any] = {"team": a.team, "window": [round(lo, 1), round(hi, 1)],
                               "frames": m.frames,
                               "coverage": _r(self.ctx.coverage(a.team, lo, hi))}
        unavailable = []
        for k, v in (("defensive_line_m", m.defensive_line_m), ("width_m", m.width_m),
                     ("compactness_m", m.compactness_m),
                     ("centroid_x", m.centroid[0] if m.centroid else None),
                     ("pressing_index", m.pressing_index)):
            if v is None:
                unavailable.append(k)
            else:
                out[k] = _r(v, 1)
        poss = possession_share(frames)
        if poss is None:
            unavailable.append("possession")
        else:
            out["possession_pct"] = poss
        out["unavailable"] = unavailable
        return out, (lo, hi)

    def _shares(self, team: str, lo: float, hi: float, data: PassData | None = None
                ) -> dict[str, Any]:
        data = data or self.ctx.first
        ws = [w for w in data.windows[team] if lo <= w.t <= hi]
        conf = [w for w in ws if w.label != UNCERTAIN]
        counts = Counter(w.label for w in conf)
        shares = {k: round(v / len(conf), 2) for k, v in counts.most_common(3)} if conf else {}
        frames = [f for f in data.frames[team] if lo <= f.t <= hi]
        m = span_metrics(frames, team, self.ctx.tcfg)
        return {"window": [round(lo, 1), round(hi, 1)], "shares": shares,
                "majority": counts.most_common(1)[0][0] if conf else UNCERTAIN,
                "confident": len(conf), "coverage": _r(self.ctx.coverage(team, lo, hi, data)),
                "line_m": _r(m.defensive_line_m, 1), "width_m": _r(m.width_m, 1)}

    def _t_compare_windows(self, st: CandidateState, a: CompareWindowsArgs):
        a0, a1 = self._window(a.a_start, a.a_end)
        b0, b1 = self._window(a.b_start, a.b_end)
        wa, wb = self._shares(a.team, a0, a1), self._shares(a.team, b0, b1)
        delta = {k: _r(wb[k] - wa[k], 1) for k in ("line_m", "width_m")
                 if wa[k] is not None and wb[k] is not None}
        same = self.ctx.fam(wa["majority"]) == self.ctx.fam(wb["majority"])
        return {"team": a.team, "a": wa, "b": wb, "delta": delta, "same_majority_family": same,
                "rules": self.rules_block(st)}, (min(a0, b0), max(a1, b1))

    # ---------------------------------------------------------------- vision tools
    def _t_check_frame_quality(self, st: CandidateState, a: QualityArgs):
        lo, hi = self._window(a.start_s, a.end_s)
        if self.ctx.backend == "video":
            return self._video_quality(st, lo, hi)
        frames = [f for f in self.ctx.match.frames if lo <= f.t <= hi]
        if not frames:
            raise _ToolFailure("no_frames", f"no frames in {lo:.0f}-{hi:.0f} s")
        qs = [f.quality for f in frames if f.quality is not None]
        h_ok = float(np.mean([q.homography_ok for q in qs])) if qs else 1.0
        cut = any(q.camera_cut for q in qs)
        players = [p for f in frames for p in f.players if p.team != "referee"]
        unknown = sum(p.team == "unknown" for p in players) / max(1, len(players))
        # no video: positions are exact by construction, so a synthetic "cut" (switch to the
        # broadcast-window view) is reported but cannot invalidate the geometry
        st.geometry = Geometry(h_ok, 0.0, 0.0, False)
        cov = self._coverage(lo, hi)
        problems = self._coverage_problems(cov)
        if h_ok < self.ctx.vcfg.min_homography_ok_share:
            problems.append(f"homography ok in {h_ok:.0%} of frames")
        if cut:
            problems.append("view switches (synthetic broadcast window; positions unaffected)")
        st.looked = True
        self._update_verdict(st)
        out = {"backend": self.ctx.backend, "window": [round(lo, 1), round(hi, 1)],
               "frames_checked": len(frames), "homography_ok_share": _r(h_ok),
               "camera_motion": "not measured (no video)", "camera_cut": cut,
               "coverage": cov, "unknown_share": _r(unknown),
               "ok": st.verdict.verdict != "refuse", "problems": problems[:4],
               "rules": self.rules_block(st)}
        st.quality = {k: v for k, v in out.items() if k != "rules"}
        return out, (lo, hi)

    def _coverage(self, lo: float, hi: float) -> dict[str, float | None]:
        return {s: _r(self.ctx.coverage(s, lo, hi)) for s in ("home", "away")}

    def _coverage_problems(self, cov: dict[str, float | None]) -> list[str]:
        m = self.ctx.vcfg.min_coverage
        return [f"{s} coverage {c:.2f} < {m:.2f}" for s, c in cov.items()
                if c is not None and c < m]

    def _video_quality(self, st: CandidateState, lo: float, hi: float):
        """OpenCV on the video: re-anchored geometry, camera motion / zoom, cuts
        (`vision.VideoBackend.quality`); player coverage from the stored MatchState."""
        vb = self._need_video()
        try:
            q = vb.quality(lo, hi)
        except VisionError as exc:
            raise _ToolFailure("vision_error", str(exc), {"retryable": False}) from exc
        st.geometry = q.geometry
        cov = self._coverage(lo, hi)
        problems = problems_of(q, self.ctx.cfg) + self._coverage_problems(cov)
        st.looked = True
        self._update_verdict(st)
        out = {"backend": "video", "view": self.ctx.view,
               "window": [round(lo, 1), round(hi, 1)], **q.summary(), "coverage": cov,
               "ok": st.verdict.verdict != "refuse", "problems": problems[:4],
               "opencv_ms": q.opencv_ms, "rules": self.rules_block(st)}
        st.quality = {k: v for k, v in out.items() if k != "rules"}
        return out, (lo, hi)

    def _t_reanalyse_window(self, st: CandidateState, a: ReanalyseArgs):
        lo, hi = self._window(a.start_s, a.end_s)
        if a.event_id and a.event_id != st.cand.id:
            raise _NotAllowed(f"this conversation verifies {st.cand.id}, not {a.event_id}")
        if st.reanalyses >= int(self.cfg["limits"]["max_reanalyses_per_candidate"]):
            raise _NotAllowed("re-analysis limit for this candidate reached")
        if self.ctx.backend == "video":
            return self._video_reanalyse(st, a, lo, hi)
        st.reanalyses += 1
        data = self.ctx.reanalyse_tactics(lo, hi)
        out: dict[str, Any] = {
            "backend": self.ctx.backend,
            "note": f"no video: tactics re-run on the MatchState at {data.sample_fps:g} fps "
                    f"(requested {a.sample_fps})",
            "window": [round(lo, 1), round(hi, 1)], "sample_fps": data.sample_fps}
        return self._reanalysis_result(st, a, data, lo, hi, out), (lo, hi)

    def _video_reanalyse(self, st: CandidateState, a: ReanalyseArgs, lo: float, hi: float):
        """OpenCV perception re-run on the window (`vision.VideoBackend.reanalyse`): budget
        refusal before running, disk cache, then the tactics engine at `sample_fps`."""
        vb = self._need_video()
        allowed = self.reanalysis_fps()
        if a.sample_fps not in allowed:
            raise _ToolFailure("fps_not_allowed", f"the {self.ctx.view} view allows "
                               f"sample_fps {allowed}", {"retryable": True})
        lo, hi = snap(lo, hi, vb.vc.grid_s, self.ctx.footage)
        try:
            r = vb.reanalyse(lo, hi, float(a.sample_fps))
        except OverBudget as exc:
            raise _ToolFailure("over_budget", str(exc), {
                "max_window_s_at_this_fps": exc.max_window_s, "retryable": True}) from exc
        except VisionError as exc:
            raise _ToolFailure("vision_error", str(exc), {"retryable": False}) from exc
        st.reanalyses += 1
        data = self.ctx.tactics_pass(r.match, r.fps, (lo, hi))
        out: dict[str, Any] = {
            "backend": "video", "window": [round(lo, 1), round(hi, 1)],
            "sample_fps": r.fps, "frames": len(r.match.frames),
            "processing_s": round(r.processing_s, 1),
            "cache": "hit" if r.cache_hit else "miss"}
        return self._reanalysis_result(st, a, data, lo, hi, out), (lo, hi)

    def _reanalysis_result(self, st: CandidateState, a: ReanalyseArgs, data: PassData,
                           lo: float, hi: float, out: dict[str, Any]) -> dict[str, Any]:
        """Labels, candidates and (with event_id) the comparison with this candidate, shared
        by all backends; a pass that covers the required span replaces the first pass."""
        out["coverage"] = {s: _r(self.ctx.coverage(s, lo, hi, data)) for s in ("home", "away")}
        teams = [st.cand.team] if a.event_id else ["home", "away"]
        out["labels"] = {t: self._strip(data, t, lo, hi) for t in teams}
        out["candidates_in_window"] = [
            {"t": round(c.t, 1), "team": c.team, "from": c.from_formation, "to": c.to_formation}
            for c in data.changes if lo <= c.t <= hi][:6]
        if a.event_id:
            ev = self.ctx.evidence(st.cand, data)
            out["vs_event"] = {"event_id": st.cand.id, **{k: v for k, v in ev.summary().items()
                                                          if k != "source"},
                               "covers_required_span": ev.covers_required_span}
            if ev.covers_required_span:
                st.latest, st.second_look, st.data = ev, True, data
        st.looked = True
        self._update_verdict(st)
        out["rules"] = self.rules_block(st)
        st.reanalysis = {k: v for k, v in out.items() if k not in ("rules", "labels")}
        return out

    def _strip(self, data: PassData, team: str, lo: float, hi: float) -> dict[str, Any]:
        ws = [w for w in data.windows[team] if lo <= w.t <= hi]
        step = max(1, int(np.ceil(len(ws) / MAX_STRIP)))
        ws = ws[::step]
        if not ws:
            return {"seq": []}
        return {"start_s": round(ws[0].t, 1),
                "step_s": round(step * self.ctx.tcfg.step_s, 1),
                "seq": ["?" if w.label == UNCERTAIN else w.label for w in ws]}

    def _t_render_evidence(self, st: CandidateState, a: RenderArgs):
        if a.event_id != st.cand.id:
            raise _NotAllowed(f"this conversation verifies {st.cand.id}, not {a.event_id}")
        if st.decision != "confirmed":
            raise _NotAllowed("render_evidence needs record_decision(confirmed) first")
        c = st.cand
        try:
            img, shows, frame_t = self.evidence_image(c, st.data or self.ctx.first)
            vc = VisionConfig.from_config(self.ctx.cfg)
            path = self.evidence_dir / self.ctx.match.match_id / f"{c.id}.{vc.evidence_format}"
            size = write_image(path, img, vc.evidence_max_bytes, vc.evidence_jpeg_quality)
        except VisionError as exc:
            raise _ToolFailure("render_failed", str(exc), {"retryable": False}) from exc
        st.evidence_image = _rel(path)
        out = {"image": st.evidence_image, "backend": self.ctx.backend,
               "next": self.next_step(st), "shows": shows, "bytes": size}
        if frame_t is not None:
            out.update(frame_t=round(frame_t, 1), clock=clock(frame_t))
        lo = c.t - self.ctx.vcfg.before_s
        return out, (min(lo, frame_t or lo), c.detected_at_s + self.ctx.vcfg.lookahead_s)

    def evidence_image(self, c: Candidate, data: PassData, note: str | None = None
                       ) -> tuple[np.ndarray, list[str], float | None]:
        """The evidence picture: on video, the frame where the new shape is clearest with the
        positions and lines projected into it, above the before / after shape panels
        (`note`: an extra red banner, e.g. for a render check that is not an alert).
        Raises VisionError when the video cannot be read."""
        panels = self.shape_panels(c, data)
        img = self.render_shapes(c, panels)
        shows = [p["caption"] + (f"; {p['note']}" if p.get("note") else "") for p in panels]
        frame_t = None
        if self.ctx.backend == "video":
            vb = self._need_video()
            frame_t, players, lines = self._evidence_content(c, data)
            if frame_t is not None:
                colours = self.ctx.cfg["perception"]["debug_video"]["colours_bgr"]
                top = vb.evidence_frame(frame_t, players, lines, c.team, colours)
                head = _bar(f"{c.id}: {self.team_name(c.team)} {c.from_} -> {c.to} | video "
                            f"frame {clock(frame_t)}: players + {c.to} lines projected by "
                            "this frame's homography (OpenCV 5)", top.shape[1])
                k = top.shape[1] / img.shape[1]
                img = np.vstack([head, top, cv2.resize(img, None, fx=k, fy=k,
                                                       interpolation=cv2.INTER_AREA)])
                shows.insert(0, f"video frame {clock(frame_t)} with players and {c.to} lines")
        if note:
            img = np.vstack([_bar(note, img.shape[1], (30, 30, 170)), img])
        return img, shows, frame_t

    def _evidence_content(self, c: Candidate, data: PassData
                          ) -> tuple[float | None, dict[str, np.ndarray], list[np.ndarray]]:
        """The frame where the new shape is clearest: inside the most confident look-ahead
        window in the new formation, the sampled frame with most outfield players of the team;
        both teams' positions (pitch metres) and the team's formation lines at that frame."""
        cfg = self.ctx.tcfg
        w = self.best_window(data, c.team, c.to, c.detected_at_s,
                             c.detected_at_s + self.ctx.vcfg.lookahead_s)
        if w is None:
            return None, {}, []
        frames = data.frames[c.team]
        idx = [i for i, f in enumerate(frames) if w.t - w.window_s <= f.t <= w.t
               and len(f.outfield) >= cfg.min_players]
        if not idx:
            return None, {}, []
        # most players visible, then the frame the new template fits best: a single open-play
        # frame has players at mixed depths, and the lines drawn through it zig-zag
        tpl = build_template(c.to, cfg)
        most = max(len(frames[j].outfield) for j in idx)
        fits = {j: fit_template(frames[j].outfield[: cfg.outfield_players], tpl, cfg)
                for j in idx if len(frames[j].outfield) == most}
        i = min(fits, key=lambda j: fits[j].cost)
        f, fit = frames[i], fits[i]
        players = {s: data.frames[s][i].raw_outfield for s in ("home", "away")}
        raw = f.raw_outfield[: cfg.outfield_players]
        lines = []
        for line in range(len(tpl.lines)):
            sel = [k for k, s in enumerate(fit.assignment) if tpl.slot_line[s] == line]
            if sel:
                lp = raw[sel]
                lines.append(lp[np.argsort(lp[:, 1])])
        return float(f.t), players, lines

    def family_windows(self, data: PassData, team: str, label: str, lo: float, hi: float
                       ) -> list[WindowResult]:
        """Confident windows ending in [lo, hi] whose label is in `label`'s family."""
        fam = self.ctx.fam(label)
        return [w for w in data.windows[team] if lo - 1e-6 <= w.t <= hi + 1e-6
                and w.label != UNCERTAIN and self.ctx.fam(w.label) == fam]

    def best_window(self, data: PassData, team: str, label: str, lo: float, hi: float
                    ) -> WindowResult | None:
        """The most confident window ending in [lo, hi] whose label is in `label`'s family."""
        ws = self.family_windows(data, team, label, lo, hi)
        return max(ws, key=lambda w: (w.confidence, w.t)) if ws else None

    def own_box_share(self, data: PassData, team: str, w: WindowResult) -> float:
        """Share of the team's outfield positions inside its own penalty area in window `w`
        (frames with enough players; attacking-direction normalised: own goal line at x = 0).
        High = defending deep or a set piece, not the team's usual shape."""
        mk = Markings.from_config(self.ctx.cfg)
        half = self.ctx.tcfg.pitch_width_m / 2
        pts = [f.outfield for f in data.frames[team] if w.t - w.window_s <= f.t <= w.t
               and len(f.outfield) >= self.ctx.tcfg.min_players]
        if not pts:
            return 0.0
        p = np.vstack(pts)
        inside = ((p[:, 0] <= mk.penalty_area_depth_m)
                  & (np.abs(p[:, 1] - half) <= mk.penalty_area_width_m / 2))
        return float(inside.mean())

    def _panel_window(self, team: str, label: str, lo: float, hi: float, data: PassData
                      ) -> tuple[WindowResult, PassData, float, bool] | None:
        """(window, pass, own-box share, typical): the most confident window of the shape
        whose own-box share is at most `presentation.evidence.max_own_box_share`, latest pass
        first; if every window is packed, the most confident one (typical = False)."""
        limit = float(self.ctx.cfg["presentation"]["evidence"]["max_own_box_share"])
        fallback = None
        for d in (data, self.ctx.first):
            scored = [(w, self.own_box_share(d, team, w))
                      for w in self.family_windows(d, team, label, lo, hi)]
            ok = [x for x in scored if x[1] <= limit]
            if ok:
                w, s = max(ok, key=lambda x: (x[0].confidence, x[0].t))
                return w, d, s, True
            if scored and fallback is None:
                w, s = max(scored, key=lambda x: (x[0].confidence, x[0].t))
                fallback = (w, d, s, False)
        return fallback

    def shape_panels(self, c: Candidate, data: PassData) -> list[dict[str, Any]]:
        """Before / after: the team's frames in one window of each shape. Each panel takes the
        most confident window of its shape in which the team is not packed in its own penalty
        area (latest pass first, then the first pass); "before" looks back
        `presentation.evidence.before_search_s` from the onset (step 7: in the 45 s before the
        16:30 demo change every 4-4-2 window had the team in its own box, so the panel showed
        a set piece). If every window is packed, the most confident one is drawn and captioned
        as such; with no confident window the panel says "low visibility" (spike 15 Oct:
        averaging partial frames gave messy shapes)."""
        v, name = self.ctx.vcfg, self.team_name(c.team)
        ev = self.ctx.cfg["presentation"]["evidence"]
        spans = (((c.t - float(ev["before_search_s"]), c.t), c.from_),
                 ((c.detected_at_s, c.detected_at_s + v.lookahead_s), c.to))
        out = []
        for (lo, hi), label in spans:
            pick = self._panel_window(c.team, label, lo, hi, data)
            if pick is None:
                frames = [f for f in data.frames[c.team] if lo <= f.t <= hi]
                out.append({"label": label, "frames": frames, "low_visibility": True,
                            "caption": f"{name} {label}: low visibility, no confident {label} "
                                       f"window in {clock(lo)}-{clock(hi)}", "note": None})
                continue
            w, src, share, typical = pick
            a, b = w.t - w.window_s, w.t
            frames = [f for f in src.frames[c.team] if a <= f.t <= b
                      and len(f.outfield) >= self.ctx.tcfg.min_players]
            note = (f"usual shape: {share:.0%} of positions in own box" if typical else
                    f"ATYPICAL: {share:.0%} of positions in own box (deep defending or "
                    "set piece?)")
            out.append({"label": label, "frames": frames, "low_visibility": False,
                        "own_box_share": round(share, 2), "typical": typical,
                        "caption": f"{name} {label} {clock(a)}-{clock(b)} (most confident "
                                   f"such window, {w.confidence:.2f})", "note": note})
        return out

    def render_shapes(self, c: Candidate, panels: list[dict[str, Any]]) -> np.ndarray:
        """Two pitch panels (OpenCV drawing): the team's average shape before and after,
        attacking right; slot means from the formation fit, joined line by line."""
        cfg = self.ctx.tcfg
        model = PitchModel(cfg.pitch_length_m, cfg.pitch_width_m)
        drawn = [self._shape_panel(model, p) for p in panels]
        img = np.hstack([drawn[0], np.full((drawn[0].shape[0], 8, 3), 255, np.uint8),
                         drawn[1]])
        head = _bar(f"{c.id}: {c.from_} -> {c.to} ({clock(c.t)}), {self.ctx.backend} "
                    "backend, average shape, attacking right", img.shape[1])
        return np.vstack([head, img])

    def _shape_panel(self, model: PitchModel, panel: dict[str, Any]) -> np.ndarray:
        cfg, ppm, m = self.ctx.tcfg, 6.0, 3.0
        w = int((model.length + 2 * m) * ppm)
        h = int((model.width + 2 * m) * ppm)
        img = np.full((h, w, 3), (40, 110, 40), np.uint8)

        def px(xy: np.ndarray) -> np.ndarray:
            xy = np.asarray(xy, float).reshape(-1, 2)
            return np.stack([(xy[:, 0] + m) * ppm, (model.width - xy[:, 1] + m) * ppm],
                            1).round().astype(np.int32)

        for poly in model.lines(0.5).values():
            cv2.polylines(img, [px(poly).reshape(-1, 1, 2)], False, (225, 225, 225), 1,
                          cv2.LINE_AA)
        frames, label = panel["frames"], panel["label"]
        if panel["low_visibility"]:
            for f in frames:
                for p in f.outfield:
                    cv2.circle(img, tuple(int(v) for v in px(p)[0]), 1, (150, 200, 150), -1)
            cv2.putText(img, "LOW VISIBILITY", (w // 2 - 150, h // 2), cv2.FONT_HERSHEY_SIMPLEX,
                        1.1, (0, 215, 255), 2, cv2.LINE_AA)
        elif label != UNCERTAIN and frames:
            tpl = build_template(label, cfg)
            sums = np.zeros((len(tpl.slots), 2))
            counts = np.zeros(len(tpl.slots))
            for f in frames:
                pts = f.outfield[: cfg.outfield_players]
                fit = fit_template(pts, tpl, cfg)
                for p, s in zip(pts, fit.assignment, strict=True):
                    sums[s] += p
                    counts[s] += 1
                    cv2.circle(img, tuple(int(v) for v in px(p)[0]), 1, (150, 200, 150), -1)
            ok = counts > 0
            means = np.where(ok[:, None], sums / np.maximum(counts, 1)[:, None], np.nan)
            for line in range(len(tpl.lines)):
                idx = [i for i in np.flatnonzero(tpl.slot_line == line) if ok[i]]
                pts = means[idx][np.argsort(means[idx][:, 1])] if idx else np.zeros((0, 2))
                if len(pts) > 1:
                    cv2.polylines(img, [px(pts).reshape(-1, 1, 2)], False, (0, 215, 255), 2,
                                  cv2.LINE_AA)
                for p in pts:
                    cv2.circle(img, tuple(int(v) for v in px(p)[0]), 7, (255, 255, 255), -1,
                               cv2.LINE_AA)
                    cv2.circle(img, tuple(int(v) for v in px(p)[0]), 7, (20, 20, 20), 1,
                               cv2.LINE_AA)
        cv2.putText(img, panel["caption"], (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.48,
                    (255, 255, 255), 1, cv2.LINE_AA)
        if panel.get("note"):  # typical / atypical (packed in own box), step 7
            colour = (230, 230, 230) if panel.get("typical") else (0, 215, 255)
            cv2.putText(img, panel["note"], (8, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.48, colour, 1,
                        cv2.LINE_AA)
        cv2.putText(img, f"{len(frames)} frames", (8, h - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (230, 230, 230), 1, cv2.LINE_AA)
        return img

    # ---------------------------------------------------------------- decision / action
    def _t_record_decision(self, st: CandidateState, a: DecisionArgs):
        if a.event_id != st.cand.id:
            raise _NotAllowed(f"this conversation verifies {st.cand.id}, not {a.event_id}")
        if st.decision is not None:
            raise _NotAllowed(f"{st.cand.id} is already {st.decision}")
        allowed = allowed_decisions(st.verdict.verdict)
        if not allowed and (st.exhausted or st.second_look):
            allowed = ("uncertain",)
        if a.decision not in allowed:
            v = st.verdict
            what = (f"call a vision tool first (missing {v.missing or v.failed})"
                    if not allowed else f"allowed: {', '.join(allowed)}")
            raise _NotAllowed(f"rules verdict is '{v.verdict}' ({v.reason}); "
                              f"'{a.decision}' is not allowed; {what}")
        if a.decision == "confirmed" and not st.looked:
            raise _NotAllowed("a confirmation needs a vision check first "
                              "(check_frame_quality or reanalyse_window)")
        cites = [c.model_dump() for c in a.citations]
        self.check_citations(st, cites, a.reason)
        st.decision, st.citations = a.decision, cites
        st.reason = self.recorded_reason(st, a.decision)
        # the call's own text stays in the trace; what a coach reads is written afterwards by
        # agent/explain.py from the code reason and the cited numbers (step 7)
        st.decision_text = a.reason
        self.statuses[st.cand.id] = a.decision
        return {"ok": True, "event_status": a.decision, "recorded_reason": st.reason,
                "next": self.next_step(st)}, None

    def recorded_reason(self, st: CandidateState, decision: Decision) -> str:
        """The code-written reason of a recorded decision (`verify.decision_reason`). On a view
        whose decisions are capped (side: experimental camera) an uncertain decision leads with
        the camera, which alone keeps it from ever being alerted; what the evidence showed
        follows as detail (step 7, presentation only: the verdict is unchanged). A refusal or
        a rejection keeps its own reason."""
        base = decision_reason(st.verdict, decision)
        v, view = self.ctx.vcfg, self.ctx.view
        if (decision != "uncertain" or v.max_decision(view) == "confirmed"
                or st.verdict.verdict == "refuse"):
            return base
        trust = v.views.get(view or "", {}).get("camera_trust", "experimental")
        details = [f"second look refused, over budget ({r['message']})"
                   for r in st.results.values() if r.get("error") == "over_budget"][-1:]
        ev = st.latest
        if "view" in st.verdict.failed and ev.share_new is not None:
            details.append(f"new shape held in {ev.share_new:.0%} of {ev.confident_after} "
                           "confident windows")
        else:
            details.append(("" if st.second_look else "first pass: ") + st.verdict.reason)
        return (f"uncertain: {trust} camera ({view} view, never alerted); detail: "
                + "; ".join(details))

    def check_citations(self, st: CandidateState, cites: list[dict[str, Any]], text: str
                        ) -> None:
        """Refs must exist (and not be errors); cited times and mm:ss clocks in `text` must lie
        inside a cited tool window (+-5 s)."""
        windows = []
        for c in cites:
            info = st.refs.get(c["ref"])
            if info is None:
                raise _NotAllowed(f"citation {c['ref']} does not exist "
                                  f"(have {', '.join(st.refs)})")
            if not info.ok:
                raise _NotAllowed(f"citation {c['ref']} is an error result")
            if info.window is not None:
                windows.append(info.window)
            t = c.get("t")
            if t is not None and info.window is not None and not _inside(t, [info.window]):
                raise _NotAllowed(f"t={t} is outside {c['ref']}'s window "
                                  f"{info.window[0]:.0f}-{info.window[1]:.0f} s")
        for mm, ss in CLOCK_RE.findall(text):
            t = int(mm) * 60 + int(ss)
            if windows and not _inside(t, windows):
                raise _NotAllowed(f"clock {mm}:{ss} is outside every cited window")

    def _t_propose_alert(self, st: CandidateState, a: AlertArgs):
        if a.event_id != st.cand.id:
            raise _NotAllowed(f"this conversation verifies {st.cand.id}, not {a.event_id}")
        if st.decision != "confirmed":
            raise _NotAllowed("propose_alert needs record_decision(confirmed) first")
        if st.evidence_image is None:
            raise _NotAllowed("propose_alert needs render_evidence first")
        if st.alert_id is not None:
            raise _NotAllowed(f"alert {st.alert_id} already proposed")
        refs = REF_RE.findall(a.explanation)
        if not refs:
            raise _NotAllowed("the explanation must cite at least one tool result as [Rn]")
        self.check_citations(st, [{"ref": r} for r in refs], a.title + " " + a.explanation)
        # what the coach reads is written by code or checked against the results: the title
        # (team, shapes, clock), the verified reason, then the explanation from
        # agent/explain.py (checked model text or template). The call's own explanation text
        # stays in the trace (step 7: 7 of 14 real model texts were wrong, FAILURE_LOG 17 Oct)
        c = st.cand
        title = f"{self.team_name(c.team)}: {c.from_} -> {c.to} ({clock(c.t)})"
        text, source = st.explanation, st.explanation_source or "template"
        if not text:
            from gaffer.agent import explain

            text, source = explain.template(explain.facts(self, st)), "template"
        explanation = compose_explanation(f"{st.reason} [{st.verdict_ref}]", text, source)
        # presentation only: a suggestion that contradicts the change is replaced by code text
        from gaffer.agent import explain

        suggestion, _ = explain.checked_suggestion(a.suggestion, self.team_name(c.team),
                                                   c.from_, c.to)
        try:
            alert = self.store.create(self.ctx.match.match_id, c.id, c.t, title, explanation,
                                      suggestion, st.evidence_image)
        except AlertError as exc:
            raise _NotAllowed(str(exc)) from exc
        st.alert_id = alert.alert_id
        return {"ok": True, "alert_id": alert.alert_id, "status": alert.status,
                "evidence_image": alert.evidence_image}, None


class _NotAllowed(Exception):
    pass


class _ToolFailure(Exception):
    def __init__(self, code: str, msg: str, extra: dict[str, Any] | None = None) -> None:
        super().__init__(msg)
        self.code, self.extra = code, extra


def _inside(t: float, windows: list[tuple[float, float]]) -> bool:
    return any(a - TIME_SLACK_S <= t <= b + TIME_SLACK_S for a, b in windows)


def _bar(text: str, width: int, colour: tuple[int, int, int] = (30, 30, 30)) -> np.ndarray:
    """A one-line caption bar (OpenCV text), dark by default."""
    bar = np.full((30, width, 3), colour, np.uint8)
    cv2.putText(bar, text, (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1,
                cv2.LINE_AA)
    return bar


def _rel(p: Path) -> str:
    try:
        return p.resolve().relative_to(repo_path(".").resolve()).as_posix()
    except ValueError:
        return p.as_posix()
