"""Deterministic verification rules for candidate shape changes (docs/AGENT_DESIGN.md §4).

The rules are the judge; the LLM orchestrates and writes, and may never be less cautious than
the verdict computed here. Every threshold lives in `config.yaml: agent.verify`.

Checks (latest pass wins: once a re-analysis exists its evidence replaces the first pass):

- **G geometry** (video only): homography ok in most sampled frames, no cut, no pan/zoom.
  Fail -> ``refuse`` (a re-analysis cannot fix a moving camera).
- **F footage**: enough of the look-ahead exists after detection. Fail -> ``uncertain``.
- **R revert**: the team returns to the old shape within the look-ahead (a reverse candidate),
  or this candidate is itself the return leg of an earlier one. Fail -> ``reject``.
- **C coverage**: enough frames show >= `tactics.min_players` outfield players of the team,
  before and after. Low coverage asks for a second look (``need_more``) but never blocks a
  verdict once that look is done: persistence counts only confident windows, and a confident
  window already needs enough visible players.
- **P persistence**: share of confident look-ahead windows in the new formation family.
  ``>= persist_pass`` held, ``<= persist_fail`` -> ``reject``, between -> ``need_more``.
- **S second look** (video only): no verdict except a refusal without a re-analysis, unless F
  already fails (no second look can add footage after the clip end).
- **V view**: per-view cap (the side camera is at most ``uncertain``).

No rule reads the ball, possession or pressing (the drone pipeline never sees the ball), on
synthetic data too, so synthetic numbers transfer to real footage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from gaffer.config import load_config

Verdict = Literal["confirm", "reject", "uncertain", "refuse", "need_more"]
Decision = Literal["confirmed", "rejected", "uncertain"]
Backend = Literal["video", "synthetic", "annotation"]

DECISION_OF: dict[str, Decision] = {"confirm": "confirmed", "reject": "rejected",
                                    "uncertain": "uncertain", "refuse": "uncertain",
                                    "need_more": "uncertain"}
# what the LLM may record for each verdict (it may be more cautious, never less)
ALLOWED: dict[str, tuple[Decision, ...]] = {
    "confirm": ("confirmed", "uncertain"),
    "reject": ("rejected",),
    "uncertain": ("uncertain", "rejected"),
    "refuse": ("uncertain", "rejected"),
    "need_more": (),
}
_RANK = {"confirmed": 2, "uncertain": 1, "rejected": 0}


@dataclass(frozen=True)
class VerifyConfig:
    """`agent.verify` + `agent.views` from config.yaml."""

    lookahead_s: float
    before_s: float
    min_coverage: float
    persist_pass: float
    persist_fail: float
    min_confident_windows: int
    min_footage_frac: float
    min_homography_ok_share: float
    max_shift_px_per_s: float
    max_zoom_change: float
    views: dict[str, dict[str, Any]] = field(default_factory=dict)
    # R: a return leg is rejected only when the new shape does not persist (17 Oct experiment)
    return_leg_needs_failed_persistence: bool = False

    @classmethod
    def from_config(cls, cfg: dict[str, Any] | None = None, **overrides: Any) -> VerifyConfig:
        cfg = cfg if cfg is not None else load_config()
        a = cfg["agent"]
        v, g = a["verify"], a["verify"]["geometry"]
        values = dict(
            lookahead_s=float(v["lookahead_s"]), before_s=float(v["before_s"]),
            min_coverage=float(v["min_coverage"]), persist_pass=float(v["persist_pass"]),
            persist_fail=float(v["persist_fail"]),
            min_confident_windows=int(v["min_confident_windows"]),
            min_footage_frac=float(v["min_footage_frac"]),
            min_homography_ok_share=float(g["min_homography_ok_share"]),
            max_shift_px_per_s=float(g["max_shift_px_per_s"]),
            max_zoom_change=float(g["max_zoom_change"]),
            views=dict(a.get("views") or {}),
            return_leg_needs_failed_persistence=bool(
                v.get("return_leg_needs_failed_persistence", False)),
        )
        values.update(overrides)
        return cls(**values)

    def max_decision(self, view: str | None) -> Decision:
        """The strongest decision allowed for a camera view (no view: no cap)."""
        if view is None:
            return "confirmed"
        return self.views.get(view, {}).get("max_decision", "confirmed")


@dataclass(frozen=True)
class Candidate:
    """A candidate shape change as the agent sees it (contract event + engine timing)."""

    id: str
    team: str
    t: float  # estimated onset
    detected_at_s: float
    from_: str
    to: str
    confidence: float
    evidence: str = ""


@dataclass
class PassEvidence:
    """What one perception pass (first pass or a re-analysis) says about one candidate."""

    source: Literal["first_pass", "reanalysis"]
    coverage_before: float | None  # share of frames with enough outfield players
    coverage_after: float | None
    share_new: float | None  # new family share of confident look-ahead windows
    confident_after: int  # confident look-ahead windows
    windows_after: int  # all look-ahead windows
    reverted_after_s: float | None  # reverse candidate detected this long after detection
    return_of: str | None  # id of the earlier candidate this one reverses
    footage_frac: float  # share of the look-ahead that exists
    covers_required_span: bool = True

    def summary(self) -> dict[str, Any]:
        """Compact, LLM-facing view (rounded)."""
        def r(v: float | None, n: int = 2) -> float | None:
            return None if v is None else round(float(v), n)

        return {"source": self.source, "coverage_before": r(self.coverage_before),
                "coverage_after": r(self.coverage_after), "after_share_new": r(self.share_new),
                "confident_after": self.confident_after,
                "reverted_after_s": r(self.reverted_after_s, 0), "return_of": self.return_of,
                "footage_frac": r(self.footage_frac)}


@dataclass
class Geometry:
    """`check_frame_quality` result on real video."""

    homography_ok_share: float
    shift_px_per_s_max: float
    zoom_change_max: float
    camera_cut: bool


@dataclass
class VerdictResult:
    verdict: Verdict
    failed: list[str]
    missing: list[str]
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "failed": self.failed, "missing": self.missing}


def geometry_problems(g: Geometry, cfg: VerifyConfig) -> list[str]:
    """Why the camera geometry cannot be trusted (empty list: ok)."""
    out = []
    if g.homography_ok_share < cfg.min_homography_ok_share:
        out.append(f"homography ok in {g.homography_ok_share:.0%} of frames")
    if g.camera_cut:
        out.append("camera cut")
    if g.shift_px_per_s_max > cfg.max_shift_px_per_s:
        out.append(f"camera moves {g.shift_px_per_s_max:.0f} px/s")
    if g.zoom_change_max > cfg.max_zoom_change:
        out.append(f"zoom changes {g.zoom_change_max:.0%}")
    return out


def evaluate(ev: PassEvidence | None, cfg: VerifyConfig, *, backend: Backend = "synthetic",
             view: str | None = None, geometry: Geometry | None = None,
             second_look: bool = False) -> VerdictResult:
    """The rules verdict for one candidate given the latest evidence (see module docstring)."""
    if geometry is not None:
        probs = geometry_problems(geometry, cfg)
        if probs:
            return VerdictResult("refuse", ["geometry"], [],
                                 "camera geometry not valid: " + ", ".join(probs))
    missing: list[str] = []
    if backend == "video":
        if geometry is None:
            missing.append("quality_check")
        if not second_look:
            missing.append("second_look")
    if ev is None:
        return VerdictResult("need_more", [], missing or ["evidence"], "no evidence yet")
    covs = (ev.coverage_before, ev.coverage_after)
    low_cov = any(c is None or c < cfg.min_coverage for c in covs)
    if low_cov and not second_look and "second_look" not in missing:
        # C is a trigger for a second look, not a verdict: a confident window already needs
        # >= min_players outfield players (dev seeds 42-52: as a hard gate it blocked 13 of
        # 39 real changes, all with >= 4 confident look-ahead windows; FAILURE_LOG 15 Oct)
        missing.append("second_look")
    v = _evaluate_pass(ev, cfg, view)
    if "footage" in v.failed:
        # F is a fact about the window bounds, the same on every pass: no second look can add
        # footage after the clip end (real drone, 15 Oct: 477 s of 1,545 s of re-analysis went
        # to 4 such candidates, no decision changed; skipped since 16 Oct, user-approved)
        missing = [m for m in missing if m != "second_look"]
    if missing and v.verdict != "need_more":
        # no verdict without the second look (real video: a first-pass revert can be a
        # perception artefact); the first-pass hint stays in the reason
        cov = min(c or 0.0 for c in covs)
        why = f"coverage {cov:.0%}; " if low_cov else ""
        return VerdictResult("need_more", v.failed + (["coverage"] if low_cov else []), missing,
                             f"{why}first pass suggests {v.verdict}: {v.reason}")
    if missing:
        v.missing = sorted(set(v.missing) | set(missing))
    return v


def _evaluate_pass(ev: PassEvidence, cfg: VerifyConfig, view: str | None) -> VerdictResult:
    """F, R, P and V on one pass of evidence (C is handled in `evaluate`)."""
    missing: list[str] = []
    if ev.footage_frac < cfg.min_footage_frac:
        return VerdictResult("uncertain", ["footage"], [],
                             f"only {ev.footage_frac:.0%} of the {cfg.lookahead_s:.0f} s "
                             "look-ahead exists after detection")
    if ev.return_of is not None and not (cfg.return_leg_needs_failed_persistence
                                         and _persists(ev, cfg)):
        return VerdictResult("reject", ["revert"], [],
                             f"returns to the shape held before {ev.return_of}")
    if ev.reverted_after_s is not None:
        return VerdictResult("reject", ["revert"], [],
                             f"reverted to the old shape {ev.reverted_after_s:.0f} s after "
                             "detection")
    known = ev.share_new is not None and ev.confident_after >= cfg.min_confident_windows
    if known and ev.share_new <= cfg.persist_fail:
        return VerdictResult("reject", ["persistence"], [],
                             f"new shape held in only {ev.share_new:.0%} of "
                             f"{ev.confident_after} confident windows after detection")
    if not known:
        return _need_more(["persistence"], missing,
                          f"only {ev.confident_after} confident windows after detection")
    if ev.share_new < cfg.persist_pass:
        return _need_more(["persistence"], missing,
                          f"new shape held in {ev.share_new:.0%} of windows (inconclusive)")
    if cfg.max_decision(view) != "confirmed":
        return VerdictResult("uncertain", ["view"], [],
                             f"held in {ev.share_new:.0%} of windows, but the {view} camera is "
                             "experimental: not alerted")
    return VerdictResult("confirm", [], [],
                         f"new shape held in {ev.share_new:.0%} of {ev.confident_after} "
                         f"confident windows over {cfg.lookahead_s:.0f} s, no revert")


def _persists(ev: PassEvidence, cfg: VerifyConfig) -> bool:
    """P passes over the look-ahead and no reverse change was detected inside it."""
    return (ev.reverted_after_s is None and ev.share_new is not None
            and ev.confident_after >= cfg.min_confident_windows
            and ev.share_new >= cfg.persist_pass)


def _need_more(failed: list[str], missing: list[str], reason: str) -> VerdictResult:
    return VerdictResult("need_more", failed, missing, reason)


def allowed_decisions(verdict: Verdict) -> tuple[Decision, ...]:
    """Decisions the LLM may record for a verdict (§4: never less cautious than the rules)."""
    return ALLOWED[verdict]


def decision_reason(v: VerdictResult, decision: Decision) -> str:
    """The code-written reason for a recorded decision: the primary reason everywhere a decision
    is shown (alerts, verified timeline, report). It restates the rules verdict and, when the
    recorded decision is more cautious than the verdict, says so; it never contradicts it. The
    model's own text is kept apart as the "explanation" (spike 15 Oct: 1 of 10 model reasons
    contradicted its verdict, FAILURE_LOG)."""
    if DECISION_OF[v.verdict] == decision and v.verdict != "need_more":
        return v.reason
    if v.verdict == "need_more":
        return f"no verdict after the evidence budget: {v.reason}"
    return f"rules: {v.verdict} ({v.reason}); recorded as {decision} (more cautious)"


def cap(decision: Decision, limit: Decision) -> Decision:
    """The more cautious of two decisions (confirmed > uncertain > rejected)."""
    return decision if _RANK[decision] <= _RANK[limit] else limit


def rules_decision(first: PassEvidence, reanalysis: PassEvidence | None, cfg: VerifyConfig, *,
                   backend: Backend = "synthetic", view: str | None = None,
                   geometry: Geometry | None = None) -> tuple[Decision, VerdictResult, bool]:
    """The rules-only policy (eval arm b, and the LLM fallback).

    First pass -> verdict; if it needs more and a re-analysis is available, the re-analysis
    replaces the first pass; a verdict still needing more becomes uncertain.
    Returns (decision, final verdict, re-analysis used).
    """
    v = evaluate(first, cfg, backend=backend, view=view, geometry=geometry, second_look=False)
    used = False
    if v.verdict == "need_more" and reanalysis is not None:
        used = True
        v = evaluate(reanalysis, cfg, backend=backend, view=view, geometry=geometry,
                     second_look=True)
    return DECISION_OF[v.verdict], v, used
