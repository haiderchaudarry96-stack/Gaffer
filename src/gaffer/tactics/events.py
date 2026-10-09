"""Per-team formation change detector with hysteresis.

The detector walks the rolling-window labels of one team. A label different from the current
formation becomes a *challenger*; it must be seen for at least `min_persist_s` (counting only
confident windows) before a `shape_change` event is emitted. Uncertain windows pause the clock
without resetting it, unless the uncertain stretch exceeds `max_uncertain_gap_s`. A challenger
that is interrupted by the current formation or by another label starts over, so short
flickers (counter-attacks, a 3 s glitch) never become events.

Labels are compared by *family* (`formations.equivalent`): a 3-5-2 that looks like a 5-3-2
without the ball is the same system, not a change. The reported formation of a family is the
member seen most often.

The first formation of the match becomes the baseline silently. Every event has
`status: "candidate"`: deciding whether it is real is the agent's job (Phase 3).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np

from gaffer.schema import Event, Side
from gaffer.tactics.common import TacticsConfig
from gaffer.tactics.formation import UNCERTAIN, WindowResult, parse_formation

LINE_NAMES = {2: ["back line", "front line"],
              3: ["back line", "midfield", "front line"],
              4: ["back line", "deep midfield", "attacking midfield", "front line"]}


@dataclass
class DetectedChange:
    """A candidate change plus engine-internal timing that is not part of the contract."""

    team: Side
    t: float  # estimated onset (goes into the contract event)
    detected_at_s: float  # when the detector could first know (used for delay in eval)
    from_formation: str
    to_formation: str
    confidence: float
    evidence: str

    def to_event(self, event_id: str) -> Event:
        """Contract `Event` with status `candidate`."""
        return Event(id=event_id, t=round(self.t, 1), type="shape_change", team=self.team,
                     from_=self.from_formation, to=self.to_formation,
                     confidence=round(self.confidence, 2), evidence=self.evidence,
                     status="candidate", verification=None)


def describe_lines(old: str, new: str) -> str:
    """Short, quotable line-by-line difference, e.g. 'back line 4->3, midfield 4->5'."""
    a, b = parse_formation(old), parse_formation(new)
    if len(a) == len(b):
        names = LINE_NAMES.get(len(a), [f"line {i + 1}" for i in range(len(a))])
        diffs = [f"{n} {x}->{y}" for n, x, y in zip(names, a, b, strict=True) if x != y]
        return ", ".join(diffs) if diffs else "same line counts"
    back = f"back line kept at {a[0]}" if a[0] == b[0] else f"back line {a[0]}->{b[0]}"
    return f"{len(a)} lines -> {len(b)} lines, {back}"


def detect_changes(windows: list[WindowResult], cfg: TacticsConfig) -> list[DetectedChange]:
    """Run the hysteresis detector over one team's windows (sorted by time)."""
    changes: list[DetectedChange] = []
    current: str | None = None  # family of the settled formation
    members: Counter[str] = Counter()  # labels seen inside the current family
    challenger: str | None = None
    since = 0.0  # end time of the first challenger window
    held = 0.0  # confident time the challenger has held
    last_seen = 0.0  # end time of the last confident challenger window
    support: list[WindowResult] = []
    prev_t: float | None = None

    def reset() -> None:
        nonlocal challenger, held, support
        challenger, held, support = None, 0.0, []

    for w in windows:
        dt = cfg.step_s if prev_t is None else w.t - prev_t
        prev_t = w.t
        if w.label == UNCERTAIN:
            if challenger is not None and w.t - last_seen > cfg.max_uncertain_gap_s:
                reset()
            continue
        family = cfg.family(w.label)
        if family == current:
            members[w.label] += 1
            reset()
            continue
        if family != challenger:
            challenger, since, held, support = family, w.t, 0.0, [w]
            last_seen = w.t
        else:
            held += min(dt, w.t - last_seen)
            last_seen = w.t
            support.append(w)
        if held + 1e-9 >= cfg.min_persist_s:
            new_members = Counter(s.label for s in support)
            to_label = new_members.most_common(1)[0][0]
            if current is not None:
                from_label = members.most_common(1)[0][0]
                onset = max(0.0, since - cfg.window_s / 2)
                conf = float(np.mean([s.confidence for s in support]))
                vis = float(np.mean([s.mean_visible for s in support]))
                evidence = (f"{describe_lines(from_label, to_label)}; held {held:.0f}s; "
                            f"{vis:.1f}/{cfg.outfield_players} outfield visible")
                changes.append(DetectedChange(
                    team=w.team, t=onset, detected_at_s=w.t, from_formation=from_label,
                    to_formation=to_label, confidence=conf, evidence=evidence))
            current, members = challenger, new_members
            reset()
    return changes

