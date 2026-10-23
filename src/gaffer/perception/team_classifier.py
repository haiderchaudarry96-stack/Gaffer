"""Team classification by shirt colour, with OpenCV 5.

Per detection (`shirt_feature`): a torso crop of the box (config fractions per view: from above
the drone sees shoulders around the head, from the side the shirt is the upper-middle band),
grass pixels masked out in HSV (`cv2.cvtColor`, hue/saturation band), the rest converted to
CIELAB (`cv2.cvtColor(COLOR_BGR2Lab)`) and averaged. Lightness is down-weighted (shade and
distance change L much more than the shirt's hue), so a feature is (w_L * L*, a*, b*).

Fit (`fit_team_model`, `cv2.kmeans`):
1. k-means with k = 2 on all features (k-means++ seeding, seed 42) gives two team centres;
2. gating: features further from their centre than `gate` x the median distance of that team
   are outliers; the two centres are re-fitted on the inliers (`KMEANS_USE_INITIAL_LABELS`),
   a few rounds. Outliers are the people in other colours: referee, assistant referees, staff,
   goalkeepers. They get their own k-means clusters (`other_clusters`), so the referee is never
   forced into a team;
3. naming: the two team centres are matched to the configured shirt-colour hints (home/away)
   by minimum total distance.

Per track (`TrackVoter`): each frame's label (home / away / other) is a vote; a track's label is
the majority of its last `vote_window` votes once it has `min_votes` and the majority holds
`min_share`, otherwise `unknown`. Tracks settled as `other` are resolved by position
(`resolve_others_frame`): standing in a goalkeeper zone -> goalkeeper of the team defending that
half; otherwise -> referee.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

LABELS = ("home", "away", "other")


class TeamClassifierError(RuntimeError):
    """Too few usable detections to learn the team colours."""


@dataclass(frozen=True)
class TeamSettings:
    """From config `teams` (torso fractions per view)."""

    torso: tuple[float, float, float, float]  # x0, x1, y0, y1 as fractions of the box
    grass_hue: tuple[float, float]
    grass_min_saturation: float
    min_pixels: int
    l_weight: float
    gate: float
    min_gate: float
    refit_rounds: int
    other_clusters: int
    min_fit_samples: int
    max_fit_samples: int
    vote_window: int
    min_votes: int
    min_share: float
    keeper_depth_m: float
    keeper_half_width_m: float

    @classmethod
    def from_config(cls, cfg: dict[str, Any], view: str) -> TeamSettings:
        t = cfg["teams"]
        return cls(tuple(float(v) for v in t["torso"][view]),  # type: ignore[arg-type]
                   (float(t["grass_hue"][0]), float(t["grass_hue"][1])),
                   float(t["grass_min_saturation"]), int(t["min_pixels"]),
                   float(t["l_weight"]), float(t["gate"]), float(t["min_gate"]),
                   int(t["refit_rounds"]), int(t["other_clusters"]),
                   int(t["min_fit_samples"]), int(t["max_fit_samples"]),
                   int(t["vote_window"]), int(t["min_votes"]), float(t["min_share"]),
                   float(t["keeper_zone"]["depth_m"]), float(t["keeper_zone"]["half_width_m"]))


# --------------------------------------------------------------------------- features


def _lab_to_feature(lab8: np.ndarray, l_weight: float) -> np.ndarray:
    """OpenCV 8-bit Lab (L 0..255, a/b offset 128) -> (w_L * L*, a*, b*) in CIELAB units."""
    lab8 = np.asarray(lab8, dtype=np.float32).reshape(-1, 3)
    return np.stack([lab8[:, 0] / 2.55 * l_weight, lab8[:, 1] - 128.0, lab8[:, 2] - 128.0], 1)


def shirt_feature(frame: np.ndarray, box: np.ndarray, s: TeamSettings, grass: Any = None,
                  shadows: bool = False, exclude: np.ndarray | None = None,
                  include: tuple[np.ndarray, float] | None = None,
                  owner_id: int | None = None) -> np.ndarray | None:
    """Mean colour of the non-grass pixels of the torso crop of one xywh box, or None when
    fewer than `min_pixels` remain (box mostly grass, or off the image).

    Grass is the fixed `teams.grass_hue` band, or this video's `grass` model
    (`selfcal.GrassModel`, its shadows too when `shadows`); pixels set in `exclude` (a
    full-frame mask, e.g. the projected painted lines) are left out as well. `include` =
    (mask, scale): only pixels set in this mask (e.g. the detector's foreground at its working
    scale: the player's own pixels, not grass edges or shadow rims) count, unless that leaves
    fewer than `min_pixels`. With `owner_id`, the mask is an owner image (detector
    `debug["owner"]`) and only pixels owned by this detection count: one part of a split
    blob, not the neighbour it was merged with."""
    x, y, w, h = (float(v) for v in box)
    fx0, fx1, fy0, fy1 = s.torso
    H, W = frame.shape[:2]
    x0, x1 = max(0, int(x + fx0 * w)), min(W, int(np.ceil(x + fx1 * w)))
    y0, y1 = max(0, int(y + fy0 * h)), min(H, int(np.ceil(y + fy1 * h)))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    crop = frame[y0:y1, x0:x1]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    if grass is not None:
        bg = grass.mask(hsv, shadows)
    else:
        bg = ((hsv[..., 0] >= s.grass_hue[0]) & (hsv[..., 0] <= s.grass_hue[1])
              & (hsv[..., 1] >= s.grass_min_saturation))
    if exclude is not None:
        bg = bg | (exclude[y0:y1, x0:x1] > 0)
    keep = ~bg.ravel()
    if include is not None:
        m, k = include
        mh, mw = m.shape[:2]
        u0, u1 = int(x0 * k), max(int(x0 * k) + 1, min(mw, int(np.ceil(x1 * k))))
        v0, v1 = int(y0 * k), max(int(y0 * k) + 1, min(mh, int(np.ceil(y1 * k))))
        sub = m[v0:v1, u0:u1]
        if sub.size:
            inc = cv2.resize(sub, (x1 - x0, y1 - y0), interpolation=cv2.INTER_NEAREST)
            inc = inc == owner_id if owner_id is not None else inc > 0
            if (keep & inc.ravel()).sum() >= s.min_pixels:
                keep = keep & inc.ravel()
    if keep.sum() < s.min_pixels:
        return None
    lab = cv2.cvtColor(crop, cv2.COLOR_BGR2Lab).reshape(-1, 3)[keep]
    return _lab_to_feature(lab.mean(axis=0), s.l_weight)[0]


def shirt_features(frame: np.ndarray, boxes: np.ndarray, s: TeamSettings, grass: Any = None,
                   shadows: bool = False, exclude: np.ndarray | None = None,
                   include: tuple[np.ndarray, float] | None = None,
                   owner_ids: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Features (N, 3) and a validity mask (N,) for all boxes of a frame (`owner_ids`:
    each box's id in an owner-image `include`)."""
    feats = np.zeros((len(boxes), 3), np.float32)
    ok = np.zeros(len(boxes), bool)
    for i, b in enumerate(boxes):
        f = shirt_feature(frame, b, s, grass, shadows, exclude, include,
                          None if owner_ids is None else int(owner_ids[i]))
        if f is not None:
            feats[i], ok[i] = f, True
    return feats, ok


def hex_to_feature(colour: str, l_weight: float) -> np.ndarray:
    """A '#rrggbb' shirt-colour hint in the same feature space."""
    c = colour.lstrip("#")
    if len(c) != 6:
        raise ValueError(f"shirt colour hint must be '#rrggbb', got {colour!r}")
    bgr = np.array([[[int(c[4:6], 16), int(c[2:4], 16), int(c[0:2], 16)]]], np.uint8)
    return _lab_to_feature(cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab)[0, 0], l_weight)[0]


# --------------------------------------------------------------------------- model


@dataclass
class TeamModel:
    """Two team centres (row 0 = home, row 1 = away), their gates, and the 'other' clusters."""

    centres: np.ndarray  # (2, 3)
    gates: np.ndarray  # (2,)
    other_centres: np.ndarray  # (k, 3), may be empty
    fit_samples: int
    outlier_share: float

    def classify(self, feats: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Per feature: label index into LABELS (0 home, 1 away, 2 other) and the other-cluster
        index (-1 for team labels)."""
        feats = np.asarray(feats, np.float32).reshape(-1, 3)
        if len(feats) == 0:
            return np.zeros(0, int), np.zeros(0, int)
        d = np.linalg.norm(feats[:, None] - self.centres[None], axis=2)
        lab = d.argmin(1)
        inside = d[np.arange(len(feats)), lab] <= self.gates[lab]
        if len(self.other_centres):
            # a feature closer to an 'other' centre than to its team centre is not a team shirt
            do = np.linalg.norm(feats[:, None] - self.other_centres[None], axis=2)
            inside &= d.min(1) < do.min(1)
            sub = np.where(inside, -1, do.argmin(1))
        else:
            sub = np.full(len(feats), -1)
        return np.where(inside, lab, 2), sub

    def to_dict(self) -> dict[str, Any]:
        return {"centres": self.centres.round(3).tolist(), "gates": self.gates.round(3).tolist(),
                "other_centres": self.other_centres.round(3).tolist(),
                "fit_samples": self.fit_samples, "outlier_share": round(self.outlier_share, 4)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TeamModel:
        return cls(np.array(d["centres"], np.float32), np.array(d["gates"], np.float32),
                   np.array(d["other_centres"], np.float32).reshape(-1, 3),
                   int(d["fit_samples"]), float(d["outlier_share"]))


def _gate(dm: np.ndarray, sel: np.ndarray, s: TeamSettings, sep: float,
          adaptive: dict[str, Any] | None) -> float:
    """One team's colour gate (CIELAB units) from the distances `dm[sel]` of its samples.

    Fixed rule: `gate` x their median, at least `min_gate`. Adaptive rule (`adaptive`, config
    `perception.self_calibration.gate`): `scale` x their `percentile`-th distance, bounded by
    `min_sep_frac` and `max_sep_frac` of the distance `sep` between the two team colours, so
    the gate follows this video's colour spread and how far apart the two kits are."""
    if not sel.any():
        return s.min_gate if adaptive is None else float(adaptive.get("min_sep_frac", 0.15)) * sep
    if adaptive is None:
        return max(s.min_gate, s.gate * float(np.median(dm[sel])))
    g = float(adaptive.get("scale", 1.5)) * float(np.percentile(dm[sel],
                                                                 adaptive.get("percentile", 90)))
    return float(np.clip(g, float(adaptive.get("min_sep_frac", 0.15)) * sep,
                         float(adaptive.get("max_sep_frac", 0.5)) * sep))


def fit_team_model(features: np.ndarray, hints: dict[str, str], s: TeamSettings,
                   seed: int = 42, adaptive: dict[str, Any] | None = None) -> TeamModel:
    """Learn the team colours from shirt features (see module docstring). `adaptive` replaces
    the fixed gate rule with one learnt from this video's colours (`_gate`)."""
    X = np.asarray(features, np.float32).reshape(-1, 3)
    if len(X) < s.min_fit_samples:
        raise TeamClassifierError(
            f"only {len(X)} usable player crops to learn team colours (need "
            f">= {s.min_fit_samples}); too few players visible in this video/window")
    if len(X) > s.max_fit_samples:  # even subsample, deterministic
        X = X[np.linspace(0, len(X) - 1, s.max_fit_samples).round().astype(int)]
    crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 100, 0.05)
    cv2.setRNGSeed(seed)
    _, lab, ctr = cv2.kmeans(X, 2, None, crit, 5, cv2.KMEANS_PP_CENTERS)
    lab = lab.ravel()
    inl = np.ones(len(X), bool)
    gates = np.full(2, np.inf, np.float32)
    for _ in range(max(1, s.refit_rounds)):
        d = np.linalg.norm(X[:, None] - ctr[None], axis=2)
        lab, dm = d.argmin(1), d.min(1)
        sep = float(np.linalg.norm(ctr[0] - ctr[1]))
        for k in range(2):
            sel = (lab == k) & inl if ((lab == k) & inl).any() else lab == k
            gates[k] = _gate(dm, sel, s, sep, adaptive)
        inl = dm <= gates[lab]
        if len(np.unique(lab[inl])) < 2:
            break
        _, l2, ctr = cv2.kmeans(X[inl], 2, lab[inl].astype(np.int32).reshape(-1, 1), crit, 1,
                                cv2.KMEANS_USE_INITIAL_LABELS)
    d = np.linalg.norm(X[:, None] - ctr[None], axis=2)
    lab, dm = d.argmin(1), d.min(1)
    sep = float(np.linalg.norm(ctr[0] - ctr[1]))
    prev = gates.copy()
    for k in range(2):
        sel = lab == k
        if adaptive is not None and np.isfinite(prev[k]) and (sel & (dm <= prev[k])).any():
            sel = sel & (dm <= prev[k])  # a percentile is not robust to the outliers
        gates[k] = _gate(dm, sel, s, sep, adaptive)
    out = dm > gates[lab]
    # people in other colours (referee, assistants, staff, keepers): their own clusters
    others = X[out]
    k_o = min(s.other_clusters, len(others))
    if k_o >= 1 and len(others) >= max(3, k_o):
        cv2.setRNGSeed(seed)
        _, _, o_ctr = cv2.kmeans(others, k_o, None, crit, 5, cv2.KMEANS_PP_CENTERS)
    else:
        o_ctr = np.zeros((0, 3), np.float32)
    # name the two team clusters with the shirt-colour hints (min total distance)
    H = np.stack([hex_to_feature(hints["home"], s.l_weight),
                  hex_to_feature(hints["away"], s.l_weight)])
    cost = np.linalg.norm(H[:, None] - ctr[None], axis=2)  # (hint, cluster)
    _, cols = linear_sum_assignment(cost)
    order = np.array(cols)
    return TeamModel(ctr[order].astype(np.float32), gates[order].astype(np.float32),
                     o_ctr.astype(np.float32), int(len(X)), float(out.mean()))


# --------------------------------------------------------------------------- per-track vote


class TrackVoter:
    """Majority vote over the last `vote_window` labels of each track; `unknown` until settled."""

    def __init__(self, s: TeamSettings) -> None:
        self.s = s
        self.votes: dict[int, deque[int]] = defaultdict(lambda: deque(maxlen=s.vote_window))

    def add(self, track_id: int, label: int | None) -> tuple[str, float]:
        """Add one frame's label (None = no usable crop) and return (settled label, share)."""
        v = self.votes[track_id]
        if label is not None:
            v.append(int(label))
        if len(v) < self.s.min_votes:
            return "unknown", 0.0
        counts = np.bincount(np.fromiter(v, int), minlength=len(LABELS))
        best = int(counts.argmax())
        share = float(counts[best] / len(v))
        return (LABELS[best], share) if share >= self.s.min_share else ("unknown", share)


def keeper_goal(xy: np.ndarray, length: float, width: float, s: TeamSettings) -> str | None:
    """'left' / 'right' if a pitch point lies in that goalkeeper zone, else None."""
    x, y = float(xy[0]), float(xy[1])
    if abs(y - width / 2) > s.keeper_half_width_m:
        return None
    if x <= s.keeper_depth_m:
        return "left"
    if x >= length - s.keeper_depth_m:
        return "right"
    return None


def resolve_others_frame(items: list[tuple[int, np.ndarray, np.ndarray, int]], length: float,
                         width: float, defends_left: str, s: TeamSettings
                         ) -> dict[int, tuple[str, str]]:
    """(team, role) for the detections of one frame whose track settled as 'other'.

    `items` = (detection index, its pitch position, its track's median position over the run,
    its track's length in frames). A track whose median position lies in a goalkeeper zone,
    on the pitch side of the goal line, is a goalkeeper of the team defending that half
    ("keepers go to the team whose half they stand in"). At most one per goal per frame: the
    longest track (a keeper is on screen all match; staff and spare balls behind the goal are
    not, and a first version that took the candidate nearest the goal line handed the slot to
    them, FAILURE_LOG 2026-10-14). Everyone else in 'other' colours is a referee (referee,
    assistant referees, staff). `defends_left` is the side defending the goal at x = 0.
    """
    other_side = "away" if defends_left == "home" else "home"
    out: dict[int, tuple[str, str]] = {it[0]: ("referee", "outfield") for it in items}
    best: dict[str, tuple[int, int]] = {}
    for i, _, med, n in items:
        g = keeper_goal(med, length, width, s)
        if g is None or not (0.0 <= float(med[0]) <= length):
            continue
        if g not in best or n > best[g][0]:
            best[g] = (n, i)
    for g, (_, i) in best.items():
        out[i] = (defends_left if g == "left" else other_side, "goalkeeper")
    return out
