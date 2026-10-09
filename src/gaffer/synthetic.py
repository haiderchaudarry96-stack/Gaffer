"""Synthetic 90-minute match generator with exact ground truth (Phase 1).

Movement model, per team, in the team's own attacking frame (u = depth from own goal):
- every outfield player owns a slot of the current formation template;
- the block slides with the ball (back-line height and lateral shift follow the ball), and
  stretches in possession / compresses out of possession;
- role habits: full-backs push up in possession, wide forwards and wing-backs drop out of it;
- each player has a fixed personal offset (so shapes are not textbook copies of the
  templates) plus a slow Ornstein-Uhlenbeck wander;
- the nearest defenders are pulled towards the ball (pressing);
- players chase their target with a response lag and a speed cap.

Scripted formation changes reassign slots with a minimum-movement assignment. Decoys that are
*not* formation changes: corners (players crowd the box), counter-attacks (front players
sprint) and 3-second flickers into another shape. Teams switch ends at half time.

Observation model: whole-pitch view most of the time (like the TeamTrack drone), a
ball-following broadcast window for ~30 % of the match (8-16 players in frame), detector
misses, position noise, unsettled team labels, tracker identity switches and a referee.

Everything is driven by the `synthetic` block of `config.yaml` and a seed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment

from gaffer.config import load_config
from gaffer.schema import CONTRACT_VERSION, OFF_PITCH_TOLERANCE_M
from gaffer.tactics.common import SIDES, TacticsConfig
from gaffer.tactics.formation import Template, build_template

GENERATOR = "gaffer.synthetic v1.0"


# --------------------------------------------------------------------------- schedule


@dataclass
class Change:
    team: str
    t: float
    to: str


@dataclass
class NoiseEvent:
    kind: str  # "set_piece" | "counter_attack" | "flicker"
    team: str  # the team whose action it is (corner taker / counter-attacker / flickering)
    start_s: float
    end_s: float
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Stretch:
    start_s: float
    end_s: float
    half_span_m: float


@dataclass
class Schedule:
    start: dict[str, str]
    changes: list[Change]


def match_001_schedule(cfg: dict[str, Any]) -> Schedule:
    """The scripted schedule from `synthetic.match_001`."""
    m = cfg["synthetic"]["match_001"]
    return Schedule(start=dict(m["start"]),
                    changes=[Change(c["team"], float(c["t"]), c["to"]) for c in m["changes"]])


def random_schedule(rng: np.random.Generator, cfg: dict[str, Any]) -> Schedule:
    """A random but plausible schedule (used for the extra eval matches)."""
    rs = cfg["synthetic"]["random_schedule"]
    names = list(cfg["formations"]["templates"])
    family = {n: g[0] for g in (cfg["formations"].get("equivalent") or []) for n in g}
    start, changes = {}, []
    for side in SIDES:
        current = str(rng.choice(names))
        start[side] = current
        n = int(rng.integers(rs["changes_per_team"][0], rs["changes_per_team"][1] + 1))
        times: list[float] = []
        for _ in range(200):
            if len(times) == n:
                break
            t = float(rng.uniform(rs["earliest_s"], rs["latest_s"]))
            if all(abs(t - u) >= rs["min_gap_s"] for u in times):
                times.append(round(t))
        for t in sorted(times):
            fam = family.get(current, current)
            current = str(rng.choice([f for f in names if family.get(f, f) != fam]))
            changes.append(Change(side, float(t), current))
    return Schedule(start=start, changes=sorted(changes, key=lambda c: c.t))


def _place_intervals(rng: np.random.Generator, count: int, length: tuple[float, float],
                     lo: float, hi: float, taken: list[tuple[float, float]],
                     avoid: float | None = None) -> list[tuple[float, float]]:
    """Random non-overlapping intervals inside [lo, hi], optionally not crossing `avoid`."""
    out: list[tuple[float, float]] = []
    for _ in range(count * 50):
        if len(out) == count:
            break
        d = float(rng.uniform(*length))
        a = float(rng.uniform(lo, hi - d))
        b = a + d
        if avoid is not None and a < avoid < b:
            continue
        if any(a < y + 5 and x < b + 5 for x, y in taken + out):
            continue
        out.append((round(a, 1), round(b, 1)))
    return sorted(out)


# --------------------------------------------------------------------------- simulation


class _Team:
    """State of one team during the simulation."""

    def __init__(self, side: str, formation: str, tcfg: TacticsConfig,
                 rng: np.random.Generator, mv: dict[str, Any], first_id: int):
        self.side = side
        self.tcfg = tcfg
        self.n = tcfg.outfield_players
        self.template = build_template(formation, tcfg)
        self.slot = np.arange(self.n)  # slot index of each outfield player
        off = rng.normal(0.0, mv["personal_offset_sd_m"], size=(self.n, 2))
        self.offset = np.clip(off, -mv["personal_offset_max_m"], mv["personal_offset_max_m"])
        self.wobble = np.zeros((self.n, 2))
        self.pos = np.zeros((self.n + 1, 2))  # index 0 = goalkeeper, raw pitch metres
        self.ids = np.arange(first_id, first_id + self.n + 1)

    def set_formation(self, formation: str) -> None:
        """Switch template; reassign slots so that players move as little as possible."""
        new = build_template(formation, self.tcfg)
        old_xy = _slot_geometry(self.template)[self.slot]
        cost = ((old_xy[:, None, :] - _slot_geometry(new)[None, :, :]) ** 2).sum(-1)
        rows, cols = linear_sum_assignment(cost)
        slot = np.empty(self.n, dtype=int)
        slot[rows] = cols
        self.template, self.slot = new, slot


def _slot_geometry(t: Template) -> np.ndarray:
    """Slots as (depth from back line, lateral) in metres."""
    g = t.slots.copy()
    g[:, 0] -= g[:, 0].min()
    return g


def _role_tags(t: Template) -> np.ndarray:
    """Per slot: 0 none, 1 full-back, 2 wide forward, 3 wing-back in a midfield five."""
    tags = np.zeros(len(t.slot_line), dtype=int)
    last = len(t.lines) - 1
    for line, count in enumerate(t.lines):
        idx = np.where(t.slot_line == line)[0]
        if len(idx) < 3:
            continue
        lat = t.slots[idx, 1]
        wide = idx[[int(np.argmin(lat)), int(np.argmax(lat))]]
        if line == 0 and count >= 4:
            tags[wide] = 1
        elif line == last and count == 3 and lat.max() - lat.min() > 30:
            tags[wide] = 2
        elif 0 < line < last and count == 5:
            tags[wide] = 3
    return tags


def _to_team(xy: np.ndarray, right: bool, L: float, W: float) -> np.ndarray:
    if right:
        return xy.copy()
    out = np.empty_like(xy)
    out[..., 0] = L - xy[..., 0]
    out[..., 1] = W - xy[..., 1]
    return out


_from_team = _to_team  # a 180-degree turn is its own inverse


class _Sim:
    def __init__(self, cfg: dict[str, Any], seed: int, schedule: Schedule):
        self.cfg = cfg
        self.sc = cfg["synthetic"]
        self.mv = self.sc["movement"]
        self.tcfg = TacticsConfig.from_config(cfg)
        self.L = float(cfg["pitch"]["length_m"])
        self.W = float(cfg["pitch"]["width_m"])
        self.rng = np.random.default_rng(seed)
        self.fps = float(self.sc["fps"])
        self.dt = 1.0 / self.fps
        self.duration = float(self.sc["duration_s"])
        self.half = float(self.sc["half_time_s"])
        self.schedule = schedule
        n = self.tcfg.outfield_players
        self.teams = {
            "home": _Team("home", schedule.start["home"], self.tcfg, self.rng, self.mv, 1),
            "away": _Team("away", schedule.start["away"], self.tcfg, self.rng, self.mv, n + 2),
        }
        self.next_id = 2 * (n + 1) + 1
        self.ref_id = 0
        self.ball = np.array([self.L / 2, self.W / 2])
        self.ref = self.ball + np.array([-8.0, 10.0])
        self.possession = "home"
        self.next_poss = self._poss_duration()
        self.waypoint = self.ball.copy()
        self.next_wp = 0.0
        self.noise = self._make_noise()
        self.stretches = self._make_stretches()
        self.cam_x = self.L / 2

    # ---- setup helpers
    def _poss_duration(self) -> float:
        return float(self.rng.exponential(self.sc["ball"]["possession_mean_s"])) + 2.0

    def _make_noise(self) -> list[NoiseEvent]:
        ne = self.sc["noise_events"]
        rng = self.rng
        taken: list[tuple[float, float]] = []
        events: list[NoiseEvent] = []
        specs = [("set_piece", ne["set_pieces"], tuple(ne["set_piece_s"])),
                 ("counter_attack", ne["counters"], tuple(ne["counter_s"])),
                 ("flicker", ne["flickers"], (ne["flicker_s"], ne["flicker_s"]))]
        n = self.tcfg.outfield_players
        for kind, count_range, length in specs:
            count = int(rng.integers(count_range[0], count_range[1] + 1))
            spans = _place_intervals(rng, count, length, 60.0, self.duration - 60.0, taken,
                                     avoid=self.half)
            taken += spans
            for a, b in spans:
                team = str(rng.choice(SIDES))
                data: dict[str, Any] = {}
                if kind == "set_piece":
                    data = {"corner_v": float(rng.choice([1.0, self.W - 1.0])),
                            "att_box": np.column_stack([rng.uniform(89, 100, n),
                                                        rng.uniform(22, self.W - 22, n)]),
                            "def_box": np.column_stack([rng.uniform(2, 15, n),
                                                        rng.uniform(20, self.W - 20, n)])}
                elif kind == "counter_attack":
                    data = {"ahead": rng.uniform(-3, 8, n), "start_v": rng.uniform(15, 53)}
                else:
                    data = {"formation": str(rng.choice(self.tcfg.template_names))}
                events.append(NoiseEvent(kind, team, a, b, data))
        return sorted(events, key=lambda e: e.start_s)

    def _make_stretches(self) -> list[Stretch]:
        cam = self.sc["camera"]
        target = cam["broadcast_fraction"] * self.duration
        if target <= 0:
            return []
        mean_len = float(np.mean(cam["broadcast_stretch_s"]))
        count = max(1, int(round(target / mean_len)))
        spans = _place_intervals(self.rng, count, tuple(cam["broadcast_stretch_s"]), 30.0,
                                 self.duration - 30.0, [])
        return [Stretch(a, b, float(self.rng.uniform(*cam["half_span_m"]))) for a, b in spans]

    # ---- per-step logic
    def attacks_right(self, side: str, t: float) -> bool:
        first = self.sc["teams"][side]["attacking_direction_first_half"] == "right"
        return first if t < self.half else not first

    def active_noise(self, t: float) -> NoiseEvent | None:
        for e in self.noise:
            if e.start_s <= t < e.end_s:
                return e
        return None

    def update_ball(self, t: float, noise: NoiseEvent | None) -> str | None:
        """Move the ball; return the possession label for this frame."""
        b = self.sc["ball"]
        rng = self.rng
        if noise is not None and noise.kind == "set_piece":
            right = self.attacks_right(noise.team, t)
            frac = (t - noise.start_s) / (noise.end_s - noise.start_s)
            if frac < 0.4:
                target = np.array([self.L - 0.5, noise.data["corner_v"]])
                self.ball = _from_team(target, right, self.L, self.W)
                self.possession = noise.team
                return "dead"
            target = _from_team(np.array([96.0, self.W / 2 + rng.normal(0, 6)]), right,
                                self.L, self.W)
            self._step_ball(target, b["max_speed_mps"])
            return noise.team
        if noise is not None and noise.kind == "counter_attack":
            self.possession = noise.team
            right = self.attacks_right(noise.team, t)
            target = _from_team(np.array([92.0, noise.data["start_v"]]), right, self.L, self.W)
            self._step_ball(target, 12.0)
            return noise.team
        if t >= self.next_poss:
            self.possession = "away" if self.possession == "home" else "home"
            self.next_poss = t + self._poss_duration()
            self.next_wp = t
        if t >= self.next_wp:
            right = self.attacks_right(self.possession, t)
            u, v = _to_team(self.ball, right, self.L, self.W)
            wu = float(np.clip(u + rng.normal(6, 15), 5, self.L - 5))
            wv = float(rng.uniform(6, self.W - 6))
            self.waypoint = _from_team(np.array([wu, wv]), right, self.L, self.W)
            self.next_wp = t + float(rng.uniform(*b["waypoint_every_s"]))
        self._step_ball(self.waypoint, b["max_speed_mps"])
        return self.possession

    def _step_ball(self, target: np.ndarray, speed: float) -> None:
        d = target - self.ball
        dist = float(np.linalg.norm(d))
        step = min(dist, speed * self.dt)
        if dist > 1e-6:
            self.ball = self.ball + d / dist * step

    def targets(self, team: _Team, t: float, poss: str | None, noise: NoiseEvent | None
                ) -> np.ndarray:
        """Target positions (keeper first) in raw pitch metres."""
        mv = self.mv
        L, W = self.L, self.W
        right = self.attacks_right(team.side, t)
        bu, bv = _to_team(self.ball, right, L, W)
        in_poss = poss == team.side
        out_poss = poss in ("home", "away") and not in_poss
        template, slot = team.template, team.slot
        if noise is not None and noise.kind == "flicker" and noise.team == team.side:
            template = build_template(noise.data["formation"], self.tcfg)
            slot = self._flicker_slots(team, template)
        geo = _slot_geometry(template)[slot]
        tags = _role_tags(template)[slot]
        back = mv["back_line_base_m"] + mv["back_line_ball_gain"] * bu
        if in_poss:
            back += mv["back_line_possession_bonus_m"]
        back = float(np.clip(back, *mv["back_line_range_m"]))
        cv = W / 2 + mv["lateral_ball_gain"] * (bv - W / 2)
        if in_poss:
            sd, sw = mv["in_possession_scale"]["depth"], mv["in_possession_scale"]["width"]
        elif out_poss:
            sd, sw = mv["out_of_possession_scale"]["depth"], mv["out_of_possession_scale"]["width"]
        else:
            sd = sw = 1.0
        u = back + geo[:, 0] * sd
        v = cv + geo[:, 1] * sw
        if in_poss:
            u = u + np.where(tags == 1, mv["fullback_push_m"], 0.0)
        if out_poss:
            u = u - np.where(tags == 2, mv["winger_drop_m"], 0.0)
            u = u - np.where(tags == 3, mv["wingback_drop_m"], 0.0)
        uv = np.column_stack([u, v]) + team.offset + team.wobble

        if noise is not None and noise.kind == "set_piece":
            depth_rank = np.argsort(np.argsort(-geo[:, 0]))  # 0 = most advanced
            if noise.team == team.side:
                crowd = depth_rank < 5
                uv[crowd] = noise.data["att_box"][crowd]
            else:
                crowd = depth_rank >= len(depth_rank) - 8
                uv[crowd] = noise.data["def_box"][crowd]
                uv[~crowd, 0] = 35.0
        elif noise is not None and noise.kind == "counter_attack" and noise.team == team.side:
            front = geo[:, 0] >= geo[:, 0].max() - 1e-6
            front[int(np.argsort(-geo[:, 0])[int(front.sum())])] = True  # one midfielder joins
            uv[front, 0] = bu + noise.data["ahead"][front]
        elif out_poss and mv["pressers"] > 0:
            ball_t = np.array([bu, bv])
            cur = _to_team(team.pos[1:], right, L, W)
            order = np.argsort(np.linalg.norm(cur - ball_t, axis=1))
            for k, pull in zip(order[: mv["pressers"]], mv["press_pull"], strict=False):
                uv[k] = uv[k] + pull * (ball_t - uv[k])

        uv[:, 0] = np.clip(uv[:, 0], 1.0, L - 1.0)
        uv[:, 1] = np.clip(uv[:, 1], 1.0, W - 1.0)
        gk = np.array([mv["goalkeeper_depth_m"] + 0.06 * bu, W / 2 + 0.15 * (bv - W / 2)])
        allp = np.vstack([gk, uv])
        return _from_team(allp, right, L, W)

    def _flicker_slots(self, team: _Team, alt: Template) -> np.ndarray:
        old_xy = _slot_geometry(team.template)[team.slot]
        cost = ((old_xy[:, None, :] - _slot_geometry(alt)[None, :, :]) ** 2).sum(-1)
        rows, cols = linear_sum_assignment(cost)
        slot = np.empty(len(rows), dtype=int)
        slot[rows] = cols
        return slot

    def move(self, team: _Team, target: np.ndarray, teleport: bool) -> None:
        mv = self.mv
        if teleport:
            team.pos = target.copy()
            return
        alpha = 1.0 - np.exp(-self.dt / mv["response_tau_s"])
        delta = (target - team.pos) * alpha
        norm = np.linalg.norm(delta, axis=1, keepdims=True)
        cap = mv["max_speed_mps"] * self.dt
        delta = np.where(norm > cap, delta / np.maximum(norm, 1e-9) * cap, delta)
        team.pos = team.pos + delta

    def step_wobble(self, team: _Team) -> None:
        tau, sd = self.mv["wobble_tau_s"], self.mv["wobble_sd_m"]
        team.wobble += (-team.wobble * self.dt / tau
                        + sd * np.sqrt(2 * self.dt / tau) * self.rng.normal(size=team.wobble.shape))

    def stretch_at(self, t: float) -> Stretch | None:
        for s in self.stretches:
            if s.start_s <= t < s.end_s:
                return s
        return None

    # ---- observation
    def observe(self, t: float, poss: str | None, stretch: Stretch | None, cut: bool
                ) -> dict[str, Any]:
        ob = self.sc["observation"]
        rng = self.rng
        L, W = self.L, self.W
        players: list[dict[str, Any]] = []
        switch_p = ob["id_switch_per_min"] * self.dt / 60.0

        def visible(x: float) -> bool:
            return stretch is None or abs(x - self.cam_x) <= stretch.half_span_m

        for side in SIDES:
            team = self.teams[side]
            for i in range(len(team.pos)):
                if rng.random() < switch_p:
                    team.ids[i] = self.next_id
                    self.next_id += 1
                x, y = team.pos[i]
                if not visible(x) or rng.random() < ob["miss_prob"]:
                    continue
                x += rng.normal(0, ob["position_noise_m"])
                y += rng.normal(0, ob["position_noise_m"])
                if not (-OFF_PITCH_TOLERANCE_M <= x <= L + OFF_PITCH_TOLERANCE_M
                        and -OFF_PITCH_TOLERANCE_M <= y <= W + OFF_PITCH_TOLERANCE_M):
                    continue
                label = "unknown" if rng.random() < ob["unknown_prob"] else side
                role = "goalkeeper" if (i == 0 and ob["label_goalkeepers"]) else "outfield"
                players.append({"track_id": int(team.ids[i]), "team": label, "role": role,
                                "x": round(float(x), 2), "y": round(float(y), 2),
                                "confidence": round(float(rng.uniform(0.6, 0.99)), 2),
                                "interpolated": False})
        if ob["include_referee"] and visible(self.ref[0]):
            players.append({"track_id": self.ref_id, "team": "referee", "role": "outfield",
                            "x": round(float(self.ref[0]), 2), "y": round(float(self.ref[1]), 2),
                            "confidence": 0.9, "interpolated": False})
        n_det = sum(1 for p in players if p["team"] != "referee")
        return {
            "t": round(t, 2), "players": players,
            "ball": {"x": round(float(self.ball[0]), 2), "y": round(float(self.ball[1]), 2),
                     "visible": True},
            "possession": poss,
            "quality": {"players_detected": n_det, "homography_ok": True,
                        "reprojection_error_m": None, "camera_cut": cut},
        }

    # ---- main loop
    def run(self) -> list[dict[str, Any]]:
        frames: list[dict[str, Any]] = []
        changes = sorted(self.schedule.changes, key=lambda c: c.t)
        ci = 0
        n_steps = int(round(self.duration * self.fps))
        prev_stretch: Stretch | None = None
        for k in range(n_steps):
            t = k * self.dt
            teleport = k == 0
            if abs(t - self.half) < self.dt / 2:
                teleport = True
                self.ball = np.array([self.L / 2, self.W / 2])
                self.possession = "away"
                self.next_poss = t + self._poss_duration()
            while ci < len(changes) and changes[ci].t <= t:
                self.teams[changes[ci].team].set_formation(changes[ci].to)
                ci += 1
            noise = self.active_noise(t)
            poss = self.update_ball(t, noise)
            for side in SIDES:
                team = self.teams[side]
                self.step_wobble(team)
                self.move(team, self.targets(team, t, poss, noise), teleport)
            ref_target = self.ball + np.array([-8.0, 10.0 if self.ball[1] < self.W / 2 else -10.0])
            ref_target = np.clip(ref_target, [1.0, 1.0], [self.L - 1.0, self.W - 1.0])
            self.ref = self.ref + (ref_target - self.ref) * (1 - np.exp(-self.dt / 2.0))

            stretch = self.stretch_at(t)
            cut = stretch is not prev_stretch
            if stretch is not None:
                if cut:
                    self.cam_x = float(self.ball[0])
                tau = self.sc["camera"]["pan_tau_s"]
                self.cam_x += (self.ball[0] - self.cam_x) * (1 - np.exp(-self.dt / tau))
            prev_stretch = stretch
            frames.append(self.observe(t, poss, stretch, cut and k > 0))
        return frames


# --------------------------------------------------------------------------- public API


def _ground_truth(match_id: str, sim: _Sim) -> dict[str, Any]:
    formations, changes = [], []
    for side in SIDES:
        current, start = sim.schedule.start[side], 0.0
        for c in sorted((c for c in sim.schedule.changes if c.team == side), key=lambda c: c.t):
            formations.append({"team": side, "from_s": start, "to_s": c.t, "formation": current})
            changes.append({"team": side, "t": c.t, "from": current, "to": c.to})
            current, start = c.to, c.t
        formations.append({"team": side, "from_s": start, "to_s": sim.duration,
                           "formation": current})
    return {
        "match_id": match_id,
        "formations": formations,
        "changes": sorted(changes, key=lambda c: c["t"]),
        "noise_events": [{"kind": e.kind, "team": e.team, "start_s": e.start_s,
                          "end_s": e.end_s} for e in sim.noise],
        "visibility": [{"mode": "broadcast", "start_s": s.start_s, "end_s": s.end_s}
                       for s in sim.stretches],
    }


def generate_match(seed: int = 42, cfg: dict[str, Any] | None = None,
                   schedule: Schedule | None = None, match_id: str = "synthetic_001"
                   ) -> tuple[dict[str, Any], dict[str, Any]]:
    """Generate one match. Returns (MatchState dict, ground-truth dict).

    `schedule` defaults to the scripted `match_001` schedule from config.
    """
    cfg = cfg if cfg is not None else load_config()
    schedule = schedule or match_001_schedule(cfg)
    sim = _Sim(cfg, seed, schedule)
    frames = sim.run()
    sc = cfg["synthetic"]
    match = {
        "contract_version": CONTRACT_VERSION,
        "match_id": match_id,
        "source": "synthetic",
        "fps": float(sc["fps"]),
        "duration_s": float(sc["duration_s"]),
        "pitch": {"length_m": sim.L, "width_m": sim.W},
        "source_video": None,
        "teams": {s: dict(sc["teams"][s]) for s in SIDES},
        "periods": [
            {"name": "first_half", "start_s": 0.0, "end_s": float(sc["half_time_s"])},
            {"name": "second_half", "start_s": float(sc["half_time_s"]),
             "end_s": float(sc["duration_s"])},
        ],
        "frames": frames,
        "meta": {"generator": f"{GENERATOR} (seed {seed})", "opencv_version": None,
                 "created_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "notes": "synthetic match; ground truth in a separate file"},
    }
    return match, _ground_truth(match_id, sim)
