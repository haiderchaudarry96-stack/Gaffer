"""Per-match state the agent works on: MatchState + tactics result + per-candidate evidence.

`MatchContext` is built once per match (the tactics engine runs once) and answers the
questions the rules and tools ask: coverage of a team in a time span, the look-ahead evidence
for a candidate, and a **synthetic / annotation re-analysis**: the tactics engine re-run on a
slice of the MatchState at its full frame rate (the engine normally samples 1 fps). That
backend has no video; it is labelled as such everywhere and is never presented as OpenCV.
The video backend (OpenCV re-run of the perception pipeline, `agent/vision.py`) feeds its
re-analysed window through the same `tactics_pass`.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

import numpy as np

from gaffer.agent.verify import Backend, Candidate, PassEvidence, VerifyConfig
from gaffer.config import load_config
from gaffer.schema import MatchState, Side
from gaffer.tactics.common import SIDES, TacticsConfig, TeamFrame, extract_team_frames
from gaffer.tactics.events import DetectedChange, detect_changes
from gaffer.tactics.formation import UNCERTAIN, WindowResult, analyse_formations
from gaffer.tactics.timeline import TacticsResult, build_timeline


@dataclass
class PassData:
    """One perception pass over a span: window labels, candidates and team frames per team."""

    windows: dict[Side, list[WindowResult]]
    changes: list[DetectedChange]
    frames: dict[Side, list[TeamFrame]]
    span: tuple[float, float]
    sample_fps: float


class MatchContext:
    """Everything the agent needs about one match, computed once."""

    def __init__(self, match: MatchState, cfg: dict[str, Any] | None = None,
                 backend: Backend | None = None, view: str | None = None,
                 result: TacticsResult | None = None) -> None:
        self.cfg = cfg if cfg is not None else load_config()
        self.match = match
        self.tcfg = TacticsConfig.from_config(self.cfg)
        self.vcfg = VerifyConfig.from_config(self.cfg)
        self.backend: Backend = backend or ("synthetic" if match.source == "synthetic" else
                                            "annotation" if match.source == "annotation"
                                            else "video")
        self.view = view
        self.result = result or build_timeline(match, self.tcfg)
        frames = extract_team_frames(match, self.tcfg)
        self.first = PassData(self.result.windows, list(self.result.changes), frames,
                              self.footage, self.tcfg.sample_fps)
        self.candidates = self._candidates()
        self._reanalysis_cache: dict[tuple[float, float, float], PassData] = {}

    # ---------------------------------------------------------------- basics
    @property
    def footage(self) -> tuple[float, float]:
        start = self.match.frames[0].t if self.match.frames else 0.0
        return float(start), float(self.match.duration_s)

    def _candidates(self) -> list[Candidate]:
        """Contract events (ids) joined with the engine's detection times, in event order."""
        shape_events = [e for e in self.result.timeline.events if e.type == "shape_change"]
        out = []
        for e, c in zip(shape_events, self.result.changes, strict=True):
            out.append(Candidate(id=e.id, team=c.team, t=float(c.t),
                                 detected_at_s=float(c.detected_at_s), from_=c.from_formation,
                                 to=c.to_formation, confidence=float(c.confidence),
                                 evidence=c.evidence))
        return out

    def candidate(self, event_id: str) -> Candidate:
        for c in self.candidates:
            if c.id == event_id:
                return c
        raise KeyError(f"unknown event id {event_id!r}")

    def fam(self, formation: str | None) -> str | None:
        return self.tcfg.change_family(formation)

    def coverage(self, team: str, a: float, b: float, data: PassData | None = None
                 ) -> float | None:
        """Share of the team's sampled frames in [a, b] with >= min_players outfield players."""
        frames = (data or self.first).frames[team]
        sel = [f for f in frames if a <= f.t <= b]
        if not sel:
            return None
        return float(np.mean([len(f.outfield) >= self.tcfg.min_players for f in sel]))

    # ---------------------------------------------------------------- evidence
    def evidence(self, cand: Candidate, data: PassData | None = None) -> PassEvidence:
        """Look-ahead evidence for one candidate from one pass (default: the first pass)."""
        data = data or self.first
        v = self.vcfg
        t_det, look = cand.detected_at_s, v.lookahead_s
        end = min(self.footage[1], data.span[1])
        footage_frac = float(np.clip((end - t_det) / look, 0.0, 1.0))
        after = [w for w in data.windows[cand.team] if t_det <= w.t <= t_det + look]
        confident = [w for w in after if w.label != UNCERTAIN]
        new = self.fam(cand.to)
        share = (sum(self.fam(w.label) == new for w in confident) / len(confident)
                 if confident else None)
        old = self.fam(cand.from_)
        reverse = [c for c in data.changes if c.team == cand.team
                   and t_det < c.detected_at_s <= t_det + look and self.fam(c.to_formation) == old]
        reverted = (min(c.detected_at_s for c in reverse) - t_det) if reverse else None
        return PassEvidence(
            source="first_pass" if data is self.first else "reanalysis",
            coverage_before=self.coverage(cand.team, cand.t - v.before_s, cand.t, data),
            coverage_after=self.coverage(cand.team, t_det, t_det + look, data),
            share_new=share, confident_after=len(confident), windows_after=len(after),
            reverted_after_s=reverted, return_of=self.return_of(cand),
            footage_frac=footage_frac,
            covers_required_span=(data.span[0] <= cand.t - v.before_s + 1e-6
                                  and data.span[1] >= min(t_det + look, self.footage[1]) - 1e-6),
        )

    def return_of(self, cand: Candidate) -> str | None:
        """The earlier candidate (same team, detected within the look-ahead) that this one
        reverses, if any. Cross-candidate fact from the first pass."""
        for p in reversed(self.candidates):
            if p.id == cand.id or p.team != cand.team:
                continue
            gap = cand.detected_at_s - p.detected_at_s
            if 0 < gap <= self.vcfg.lookahead_s and self.fam(p.to) == self.fam(cand.from_) \
                    and self.fam(p.from_) == self.fam(cand.to):
                return p.id
        return None

    def required_span(self, cand: Candidate) -> tuple[float, float]:
        """Span a re-analysis must cover: [onset - before_s, detection + look-ahead]."""
        a = max(self.footage[0], cand.t - self.vcfg.before_s)
        b = min(self.footage[1], cand.detected_at_s + self.vcfg.lookahead_s)
        return float(a), float(b)

    # ---------------------------------------------------------------- re-analysis (no video)
    def reanalyse_tactics(self, start_s: float, end_s: float, sample_fps: float | None = None
                          ) -> PassData:
        """Synthetic / annotation backend: the tactics engine on [start_s - context, end_s] of
        the MatchState at `sample_fps` (default: `agent.reanalysis.synthetic_sample_fps`)."""
        rcfg = self.cfg["agent"]["reanalysis"]
        fps = float(sample_fps or rcfg["synthetic_sample_fps"])
        a = max(self.footage[0], float(start_s) - float(rcfg["context_s"]))
        b = min(self.footage[1], float(end_s))
        key = (round(a, 1), round(b, 1), fps)
        if key in self._reanalysis_cache:
            return self._reanalysis_cache[key]
        frames = [f for f in self.match.frames if a <= f.t <= b]
        sliced = self.match.model_copy(update={"frames": frames})
        data = self.tactics_pass(sliced, fps, (a, b))
        self._reanalysis_cache[key] = data
        return data

    def tactics_pass(self, match: MatchState, fps: float, span: tuple[float, float]
                     ) -> PassData:
        """The tactics engine on `match` (a MatchState slice, or a window the perception
        pipeline re-analysed on video) at `fps` frames per second."""
        tcfg = dataclasses.replace(self.tcfg, sample_fps=min(float(fps), match.fps))
        team_frames = extract_team_frames(match, tcfg)
        windows = analyse_formations(match, tcfg, team_frames)
        changes = sorted((c for s in SIDES for c in detect_changes(windows[s], tcfg)),
                         key=lambda c: (c.t, c.team))
        return PassData(windows, changes, team_frames, span, tcfg.sample_fps)
