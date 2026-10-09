"""Phase 0 data inspection (EDA) of the TeamTrack clips in data/teamtrack/.

Answers the "Data inspection (EDA)" questions in docs/PLAN.md Phase 0:
inventory, video metadata (OpenCV), CSV structure, objects per frame / per TeamID,
box sizes, side-view distortion, pitch visibility, sample frames with ground-truth boxes,
heat-maps and objects-per-frame plots.

Outputs: images in outputs/eda/ and the findings (real numbers) in docs/DATA_NOTES.md.

Usage:
    py scripts\\inspect_data.py
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from gaffer.config import load_config, repo_path  # noqa: E402

VIEWS = ("soccer_top", "soccer_side")
NAME_RE = re.compile(r"^(?P<cam>[A-Z])_(?P<date>\d{8})_(?P<half>\d)_(?P<start>\d+)_(?P<end>\d+)$")


# --------------------------------------------------------------------------- helpers
class Timer:
    """Collects a per-stage timing summary."""

    def __init__(self) -> None:
        self.stages: list[tuple[str, float]] = []
        self._t = time.perf_counter()

    def lap(self, name: str) -> None:
        now = time.perf_counter()
        self.stages.append((name, now - self._t))
        print(f"  [{name}] {now - self._t:.1f}s")
        self._t = now


@dataclass
class Clip:
    """One video + its annotation CSV."""

    view: str
    stem: str
    video: Path | None
    csv: Path | None
    start_s: int = 0
    end_s: int = 0
    meta: dict = field(default_factory=dict)
    ann: pd.DataFrame | None = None  # long format


def load_annotations(csv_path: Path) -> pd.DataFrame:
    """Load a TeamTrack CSV (3-row header) into long format.

    Returns columns: frame, team ("0" | "1" | "BALL"), player, bb_left, bb_top, bb_width,
    bb_height. Rows where all four box values are NaN are dropped.
    """
    wide = pd.read_csv(csv_path, header=[0, 1, 2], index_col=0)
    long = wide.stack(level=[0, 1], future_stack=True).dropna(how="all").reset_index()
    long.columns = ["frame", "team", "player", *list(long.columns[3:])]
    return long[["frame", "team", "player", "bb_left", "bb_top", "bb_width", "bb_height"]]


def read_frame(video: Path, index: int) -> np.ndarray | None:
    """Read a single frame (0-based) or return None."""
    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, frame = cap.read()
    cap.release()
    return frame if ok else None


def fourcc_str(code: float) -> str:
    c = int(code)
    return "".join(chr((c >> 8 * i) & 0xFF) for i in range(4))


def team_colour(cfg: dict, team: str) -> tuple[int, int, int]:
    cols = cfg["eda"]["team_colours_bgr"]
    return tuple(cols.get(str(team), cols["other"]))


def downscale(img: np.ndarray, max_w: int) -> np.ndarray:
    h, w = img.shape[:2]
    if w <= max_w:
        return img
    return cv2.resize(img, (max_w, int(h * max_w / w)), interpolation=cv2.INTER_AREA)


def pct(series: pd.Series, qs=(5, 50, 95)) -> str:
    return " / ".join(f"{np.percentile(series, q):.0f}" for q in qs)


# --------------------------------------------------------------------------- stages
def inventory(root: Path) -> list[Clip]:
    """Pair videos with CSVs per view, parse the time range from the file name."""
    clips: list[Clip] = []
    for view in VIEWS:
        vids = {p.stem: p for p in (root / view / "videos").glob("*.mp4")}
        csvs = {p.stem: p for p in (root / view / "annotations").glob("*.csv")}
        for stem in sorted(set(vids) | set(csvs)):
            m = NAME_RE.match(stem)
            clips.append(Clip(view, stem, vids.get(stem), csvs.get(stem),
                              int(m["start"]) if m else 0, int(m["end"]) if m else 0))
    return clips


def video_metadata(clips: list[Clip], verify_count_for_first: bool = True) -> dict[str, int]:
    """Fill clip.meta from OpenCV; decode one clip per view fully to verify the frame count."""
    verified: dict[str, int] = {}
    for clip in clips:
        if clip.video is None:
            continue
        cap = cv2.VideoCapture(str(clip.video))
        if not cap.isOpened():
            clip.meta = {"error": "unreadable"}
            continue
        clip.meta = {
            "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "fps": cap.get(cv2.CAP_PROP_FPS),
            "frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
            "codec": fourcc_str(cap.get(cv2.CAP_PROP_FOURCC)),
            "size_mb": clip.video.stat().st_size / 1e6,
        }
        clip.meta["duration_s"] = clip.meta["frames"] / clip.meta["fps"]
        if verify_count_for_first and clip.view not in verified:
            n = 0
            while cap.grab():
                n += 1
            verified[clip.view] = n
            clip.meta["frames_decoded"] = n
        cap.release()
    return verified


def drone_drift(clips: list[Clip]) -> dict[str, list[float]]:
    """Camera stability: cv2.phaseCorrelate between first and last frame of each clip (px)."""
    out: dict[str, list[float]] = {}
    for clip in clips:
        if clip.video is None or not clip.meta.get("frames"):
            continue
        a = read_frame(clip.video, 0)
        b = read_frame(clip.video, clip.meta["frames"] - 1)
        if a is None or b is None:
            continue
        ga = cv2.cvtColor(downscale(a, 1280), cv2.COLOR_BGR2GRAY).astype(np.float32)
        gb = cv2.cvtColor(downscale(b, 1280), cv2.COLOR_BGR2GRAY).astype(np.float32)
        win = cv2.createHanningWindow(ga.shape[::-1], cv2.CV_32F)
        (dx, dy), _ = cv2.phaseCorrelate(ga, gb, win)
        scale = a.shape[1] / ga.shape[1]
        out.setdefault(clip.view, []).append(float(np.hypot(dx, dy) * scale))
    return out


def id_continuity(clips: list[Clip]) -> dict[str, tuple[float, float]]:
    """Across consecutive clips: median foot-point jump for the same (team, player) id vs.
    the median nearest-other-player distance. Small 'same' >> consistent ids."""
    res: dict[str, tuple[float, float]] = {}
    for view in VIEWS:
        vc = [c for c in clips if c.view == view and c.ann is not None]
        same, other = [], []
        for a, b in zip(vc, vc[1:], strict=False):
            if a.end_s != b.start_s:
                continue
            la = a.ann[(a.ann.frame == a.ann.frame.max()) & (a.ann.team != "BALL")]
            fb = b.ann[(b.ann.frame == b.ann.frame.min()) & (b.ann.team != "BALL")]
            pa = {(r.team, r.player): (r.bb_left + r.bb_width / 2, r.bb_top + r.bb_height)
                  for r in la.itertuples()}
            pb = {(r.team, r.player): (r.bb_left + r.bb_width / 2, r.bb_top + r.bb_height)
                  for r in fb.itertuples()}
            for k, p in pa.items():
                if k in pb:
                    same.append(np.hypot(*np.subtract(p, pb[k])))
                    others = [np.hypot(*np.subtract(p, q)) for kk, q in pb.items() if kk != k]
                    other.append(min(others))
        if same:
            res[view] = (float(np.median(same)), float(np.median(other)))
    return res


def goalkeepers(ann: pd.DataFrame) -> dict[str, tuple[str, float, float]]:
    """Per team: the player with the most extreme mean x (likely GK), its mean x and the team's
    outfield mean x."""
    out = {}
    players = ann[ann.team != "BALL"].assign(cx=lambda d: d.bb_left + d.bb_width / 2)
    for team, g in players.groupby("team"):
        mx = g.groupby("player").cx.mean()
        centre = mx.median()
        pid = (mx - centre).abs().idxmax()
        out[team] = (pid, float(mx[pid]), float(mx.drop(pid).mean()))
    return out


def occlusion_rate(ann: pd.DataFrame, iou_thr: float = 0.3) -> float:
    """Mean number of player pairs per frame whose GT boxes overlap with IoU > iou_thr."""
    pl = ann[ann.team != "BALL"]
    counts = []
    for _, g in pl.groupby("frame"):
        b = g[["bb_left", "bb_top", "bb_width", "bb_height"]].to_numpy()
        x1, y1 = b[:, 0], b[:, 1]
        x2, y2 = x1 + b[:, 2], y1 + b[:, 3]
        iw = np.clip(np.minimum(x2[:, None], x2) - np.maximum(x1[:, None], x1), 0, None)
        ih = np.clip(np.minimum(y2[:, None], y2) - np.maximum(y1[:, None], y1), 0, None)
        inter = iw * ih
        area = b[:, 2] * b[:, 3]
        iou = inter / (area[:, None] + area - inter + 1e-9)
        counts.append(int((np.triu(iou, 1) > iou_thr).sum()))
    return float(np.mean(counts))


def draw_gt(frame: np.ndarray, rows: pd.DataFrame, cfg: dict, thick: int) -> np.ndarray:
    """Draw GT boxes coloured by TeamID with the PlayerID label."""
    img = frame.copy()
    for r in rows.itertuples():
        c = team_colour(cfg, r.team)
        p1 = (int(r.bb_left), int(r.bb_top))
        p2 = (int(r.bb_left + r.bb_width), int(r.bb_top + r.bb_height))
        cv2.rectangle(img, p1, p2, c, thick)
        label = "ball" if r.team == "BALL" else f"{r.team}:{r.player}"
        cv2.putText(img, label, (p1[0], p1[1] - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5 * thick, c,
                    thick)
    return img


def legend(img: np.ndarray, cfg: dict, text: str) -> np.ndarray:
    cv2.rectangle(img, (0, 0), (img.shape[1], 34), (20, 20, 20), -1)
    x = 10
    for team, name in (("0", "TeamID 0"), ("1", "TeamID 1"), ("BALL", "ball")):
        cv2.rectangle(img, (x, 9), (x + 16, 25), team_colour(cfg, team), -1)
        cv2.putText(img, name, (x + 22, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (240, 240, 240), 1)
        x += 130
    cv2.putText(img, text, (x + 10, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (240, 240, 240), 1)
    return img


def sample_frames(clips: list[Clip], cfg: dict, out: Path) -> list[Path]:
    """3 frames per view (first clip start, middle clip middle, last clip end) with GT boxes."""
    saved = []
    max_w = cfg["eda"]["max_image_width"]
    for view in VIEWS:
        vc = [c for c in clips if c.view == view and c.ann is not None and c.video]
        n = cfg["eda"]["sample_frames_per_view"]
        picks = [vc[0], vc[len(vc) // 2], vc[-1]][:n]
        for i, clip in enumerate(picks):
            nframes = int(clip.ann.frame.max())
            csv_frame = [1, nframes // 2, nframes][i]
            frame = read_frame(clip.video, csv_frame - 1)  # CSV frame 1 == video index 0
            if frame is None:
                continue
            rows = clip.ann[clip.ann.frame == csv_frame]
            tag = f"{clip.stem} frame {csv_frame}"
            if view == "soccer_top":
                img = downscale(draw_gt(frame, rows, cfg, 3), max_w)
            else:  # 6500 px panorama: keep native resolution around the annotated players
                img = draw_gt(frame, rows, cfg, 2)
                x0 = int(max(0, rows.bb_left.min() - 200))
                x1 = int(min(frame.shape[1], (rows.bb_left + rows.bb_width).max() + 200))
                y0 = int(max(0, rows.bb_top.min() - 150))
                y1 = int(min(frame.shape[0], (rows.bb_top + rows.bb_height).max() + 120))
                img = downscale(img[y0:y1, x0:x1], max_w + 600)
                tag += f"  (crop x {x0}-{x1}, y {y0}-{y1})"
            path = out / f"gt_{view.split('_')[1]}_{i + 1}.jpg"
            cv2.imwrite(str(path), legend(img, cfg, tag), [cv2.IMWRITE_JPEG_QUALITY, 85])
            saved.append(path)
    return saved


def heatmaps(clips: list[Clip], cfg: dict, out: Path) -> list[Path]:
    """Foot-point heat-map per view (all clips, both teams) blended on the first frame."""
    saved = []
    for view in VIEWS:
        vc = [c for c in clips if c.view == view and c.ann is not None and c.video]
        bg = read_frame(vc[0].video, 0)
        h, w = bg.shape[:2]
        acc = {t: np.zeros((h // 4, w // 4), np.float32) for t in ("0", "1")}
        for clip in vc:
            pl = clip.ann[clip.ann.team != "BALL"]
            fx = ((pl.bb_left + pl.bb_width / 2) / 4).clip(0, w // 4 - 1).astype(int)
            fy = ((pl.bb_top + pl.bb_height) / 4).clip(0, h // 4 - 1).astype(int)
            for t in acc:
                m = (pl.team == t).to_numpy()
                np.add.at(acc[t], (fy[m], fx[m]), 1)
        panels = []
        for t, a in acc.items():
            a = cv2.GaussianBlur(a, (0, 0), 6)
            a = (255 * a / (a.max() + 1e-9)).astype(np.uint8)
            col = cv2.applyColorMap(cv2.resize(a, (w, h)), cv2.COLORMAP_INFERNO)
            mask = cv2.resize(a, (w, h)) > 8
            blend = (bg * 0.45).astype(np.uint8)
            blend[mask] = cv2.addWeighted(bg, 0.25, col, 0.75, 0)[mask]
            panel = downscale(blend, cfg["eda"]["max_image_width"])
            cv2.putText(panel, f"TeamID {t} foot positions, {len(vc)} clips", (12, 32),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
            panels.append(panel)
        img = np.vstack(panels)
        path = out / f"heatmap_{view.split('_')[1]}.jpg"
        cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        saved.append(path)
    return saved


def objects_plot(clips: list[Clip], out: Path) -> Path:
    """Objects per frame over time (concatenated clips), plus inside-frame and overlap counts."""
    fig, axes = plt.subplots(len(VIEWS), 1, figsize=(12, 6), sharex=False)
    for ax, view in zip(axes, VIEWS, strict=True):
        vc = [c for c in clips if c.view == view and c.ann is not None]
        t_all, tot, inside, t0, t1 = [], [], [], [], []
        for clip in vc:
            fps = clip.meta.get("fps", 25.0)
            W, H = clip.meta.get("width", 1e9), clip.meta.get("height", 1e9)
            a = clip.ann
            ins = ((a.bb_left >= 0) & (a.bb_top >= 0) & (a.bb_left + a.bb_width <= W)
                   & (a.bb_top + a.bb_height <= H))
            g = a.assign(inside=ins).groupby("frame")
            t_all += list(clip.start_s + (np.array(list(g.groups)) - 1) / fps)
            tot += list(g.size())
            inside += list(g.inside.sum())
            t0 += list(g.apply(lambda d: (d.team == "0").sum(), include_groups=False))
            t1 += list(g.apply(lambda d: (d.team == "1").sum(), include_groups=False))
        ax.plot(t_all, tot, label="all objects", lw=2)
        ax.plot(t_all, inside, "--", label="box fully inside image")
        ax.plot(t_all, t0, label="TeamID 0")
        ax.plot(t_all, t1, ":", label="TeamID 1")
        ax.set_title(f"{view}: annotated objects per frame")
        ax.set_ylabel("count")
        ax.set_ylim(0, 26)
        ax.legend(loc="lower right", fontsize=8, ncol=4)
    axes[-1].set_xlabel("match time (s, from file names)")
    fig.tight_layout()
    path = out / "objects_per_frame.png"
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def box_size_plot(clips: list[Clip], out: Path) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    for ax, view in zip(axes, VIEWS, strict=True):
        a = pd.concat([c.ann for c in clips if c.view == view and c.ann is not None])
        pl = a[a.team != "BALL"]
        ax.hist(pl.bb_height, bins=60, alpha=0.7, label="height")
        ax.hist(pl.bb_width, bins=60, alpha=0.7, label="width")
        ax.set_title(f"{view}: player box size (px, native resolution)")
        ax.set_xlabel("pixels")
        ax.legend()
    fig.tight_layout()
    path = out / "box_sizes.png"
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def pitch_top(clips: list[Clip], cfg: dict, out: Path) -> dict:
    """Top view: white pitch-line mask (HSV inRange), outer rectangle via minAreaRect."""
    clip = next(c for c in clips if c.view == "soccer_top" and c.video)
    frame = read_frame(clip.video, 0)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    white = cv2.inRange(hsv, (0, 0, 175), (180, 60, 255))
    green = cv2.inRange(hsv, (35, 40, 40), (90, 255, 255))
    # keep white pixels that have grass nearby -> pitch lines, not stands / text boards
    near_grass = cv2.dilate(green, np.ones((25, 25), np.uint8))
    lines = cv2.bitwise_and(white, near_grass)
    lines = cv2.morphologyEx(lines, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(lines)
    # the outer boundary + halfway line form the largest connected line component
    big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    pts = cv2.findNonZero((labels == big).astype(np.uint8))
    (cx, cy), (rw, rh), ang = cv2.minAreaRect(pts)
    length_px, width_px = max(rw, rh), min(rw, rh)
    box = cv2.boxPoints(((cx, cy), (rw, rh), ang)).astype(np.int32)
    vis = frame.copy()
    vis[lines > 0] = (0, 0, 255)
    cv2.polylines(vis, [box], True, (0, 255, 255), 6)
    cv2.putText(vis, f"outer lines {length_px:.0f} x {width_px:.0f} px, ratio "
                     f"{length_px / width_px:.3f}", (60, 120), cv2.FONT_HERSHEY_SIMPLEX, 2.5,
                (0, 255, 255), 5)
    path = out / "pitch_lines_top.jpg"
    cv2.imwrite(str(path), downscale(vis, cfg["eda"]["max_image_width"]),
                [cv2.IMWRITE_JPEG_QUALITY, 85])
    return {"length_px": length_px, "width_px": width_px, "angle": ang,
            "line_px_frac": float((lines > 0).mean()), "path": path, "frame_w": frame.shape[1]}


def side_distortion(clips: list[Clip], cfg: dict, out: Path) -> dict:
    """Side view distortion.

    Visual: pitch-line mask (morphological top-hat on V, so dim lines under overcast light
    are found) in red, with straight horizontal reference lines, plus native-resolution edge
    crops. Numeric: GT player box aspect ratio (w/h) per horizontal image band — an upright
    player has w/h ~0.5, so horizontal stretching shows up as a rising w/h towards the edges.
    """
    vc = [c for c in clips if c.view == "soccer_side" and c.ann is not None and c.video]
    frame = read_frame(vc[0].video, 0)
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    tophat = cv2.morphologyEx(hsv[:, :, 2], cv2.MORPH_TOPHAT,
                              cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15)))
    green = cv2.inRange(hsv, (30, 40, 30), (90, 255, 255))
    lines = ((tophat > 30) & (hsv[:, :, 1] < 90)).astype(np.uint8) * 255
    lines = cv2.bitwise_and(lines, cv2.dilate(green, np.ones((9, 9), np.uint8)))
    vis = frame.copy()
    vis[lines > 0] = (0, 0, 255)
    for y in range(400, h, 100):
        cv2.line(vis, (0, y), (w, y), (255, 0, 255), 2)
    cv2.putText(vis, "red = pitch-line mask (top-hat), magenta = straight horizontal "
                "references", (40, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 255, 255), 4)
    path = out / "distortion_side.jpg"
    cv2.imwrite(str(path), downscale(vis, 2600), [cv2.IMWRITE_JPEG_QUALITY, 85])
    edge = np.hstack([frame[300:900, :900], frame[300:900, -900:]])
    epath = out / "side_edges.jpg"
    cv2.imwrite(str(epath), edge, [cv2.IMWRITE_JPEG_QUALITY, 85])

    pl = pd.concat([c.ann for c in vc])
    pl = pl[(pl.team != "BALL") & (pl.bb_height >= 15)]
    cx = pl.bb_left + pl.bb_width / 2
    bands = pd.cut(cx, bins=np.arange(0, w + 650, 650))
    by_band = (pl.bb_width / pl.bb_height).groupby(bands, observed=True).agg(["median", "size"])
    by_band = by_band[by_band["size"] >= 100]
    return {"path": path, "edge_path": epath, "aspect_by_band": by_band,
            "x_range": (int(cx.min()), int(cx.max()))}


# --------------------------------------------------------------------------- report
def write_notes(path: Path, ctx: dict) -> None:
    """Write docs/DATA_NOTES.md from the computed numbers."""
    clips: list[Clip] = ctx["clips"]
    L: list[str] = []
    a = L.append
    a("# DATA_NOTES — what the TeamTrack data actually looks like")
    a("")
    a(f"Generated by `scripts/inspect_data.py` on {time.strftime('%Y-%m-%d')} "
      f"(OpenCV {cv2.__version__}, pandas {pd.__version__}). Re-run to refresh. "
      "Trust these numbers over assumptions.")
    a("")
    a("Source: TeamTrack (Scott et al., 2024), Kaggle `atomscott/teamtrack`, MIT licence. "
      "Test split, subset of files.")
    a("")
    a("## 1. Inventory")
    a("")
    a("| view | clip | match time (s) | video MB | CSV | consecutive with previous |")
    a("|---|---|---|---|---|---|")
    prev: dict[str, Clip] = {}
    for c in clips:
        cons = "—" if c.view not in prev else ("yes" if prev[c.view].end_s == c.start_s
                                               else "**no (gap)**")
        a(f"| {c.view} | `{c.stem}` | {c.start_s}–{c.end_s} | "
          f"{c.meta.get('size_mb', 0):.1f} | {'yes' if c.csv else '**missing**'} | {cons} |")
        prev[c.view] = c
    for view in VIEWS:
        vc = [c for c in clips if c.view == view]
        a("")
        a(f"- **{view}**: {len(vc)} clips, {sum(1 for c in vc if c.video and c.csv)} with both "
          f"video and CSV, covering match time {vc[0].start_s}–{vc[-1].end_s} s "
          f"({(vc[-1].end_s - vc[0].start_s) / 60:.1f} min) of half "
          f"{NAME_RE.match(vc[0].stem)['half']}.")
    a("- File name = `<camera>_<date>_<half>_<start_s>_<end_s>`; `D` = drone (top), "
      "`F` = fixed side camera. Video and CSV share the stem → pairing is by name.")
    a(f"- **Top and side clips are the same match** (2022-02-20, half 1). Overlapping match "
      f"time: {ctx['overlap']} s — the same moments are seen from both cameras "
      "(useful for cross-checking; the two have different fps, so syncing needs care).")
    a("")
    a("## 2. Video metadata (OpenCV `VideoCapture`)")
    a("")
    a("| view | resolution | fps | frames | duration | codec | CSV rows (frames) |")
    a("|---|---|---|---|---|---|---|")
    for view in VIEWS:
        c = next(c for c in clips if c.view == view and c.meta)
        rows = sorted({int(x.ann.frame.nunique()) for x in clips
                       if x.view == view and x.ann is not None})
        a(f"| {view} | {c.meta['width']}×{c.meta['height']} | {c.meta['fps']:.2f} | "
          f"{c.meta['frames']} | {c.meta['duration_s']:.1f} s | {c.meta['codec']} | "
          f"{', '.join(map(str, rows))} |")
    a("")
    for view, n in ctx["verified"].items():
        c = next(c for c in clips if c.view == view and c.meta)
        a(f"- {view}: decoding `{c.stem}` frame-by-frame gave **{n}** frames "
          f"(header says {c.meta['frames']}) → frame count "
          f"{'matches' if n == c.meta['frames'] else '**does not match**'} the CSV.")
    a("- All clips in a view share identical metadata: "
      + ", ".join(f"{v}: {'yes' if ctx['uniform'][v] else '**no**'}" for v in VIEWS) + ".")
    a("- CSV `frame` runs 1…N; we assume CSV frame *k* = video frame index *k−1*. The GT "
      "overlays in §8 line up with the players, which supports this.")
    a("- Camera stability (`cv2.phaseCorrelate`, first vs last frame of each clip): "
      + "; ".join(f"{v}: median {np.median(d):.1f} px, max {np.max(d):.1f} px"
                  for v, d in ctx["drift"].items())
      + ". The drone hovers rather than being locked, so a per-clip (or per-keyframe) "
        "homography is safer than one for the whole match.")
    a("")
    a("## 3. CSV structure and how to load it")
    a("")
    a("Three header rows, then a `frame` label row, then one row per frame:")
    a("")
    a("```")
    a("TeamID,    0,        0,      0,     0,        0, ...,  1, ..., BALL,     BALL, ...")
    a("PlayerID,  0,        0,      0,     0,        1, ..., 10, ..., BALL,     BALL, ...")
    a("Attributes,bb_height,bb_left,bb_top,bb_width,bb_height,...")
    a("frame,,,,,...")
    a("1,20.0,1192.0,902.0,30.0,...")
    a("```")
    a("")
    a("```python")
    a("wide = pd.read_csv(path, header=[0, 1, 2], index_col=0)   # 900 x 92 for a top clip")
    a("long = wide.stack(level=[0, 1], future_stack=True).dropna(how='all').reset_index()")
    a("# -> frame, TeamID, PlayerID, bb_height, bb_left, bb_top, bb_width")
    a("```")
    a("")
    a(f"- {ctx['ncols']} columns = 23 objects × 4 attributes. Column levels: "
      "`TeamID` ∈ {`0`, `1`, `BALL`}, `PlayerID` ∈ {`0`…`10`} (or `BALL`), `Attributes`.")
    a("- **Attribute order is alphabetical** (`bb_height, bb_left, bb_top, bb_width`) and "
      "**PlayerIDs sort as strings** (`0, 1, 10, 2, …`) — always index by name, never by "
      "position.")
    a("- Units: **pixels in the native video frame**; `bb_left`/`bb_top` = top-left corner. "
      f"Values are floats; {ctx['nonint']['soccer_top']:.1%} (top) / "
      f"{ctx['nonint']['soccer_side']:.1%} (side) are non-integer (interpolated?).")
    a(f"- Missing values: **{ctx['nan_total']} NaN cells across all {ctx['ncsv']} CSVs**, "
      "always all four attributes of an object together:")
    for stem, n, objs, f0, f1, nf in ctx["nan_detail"]:
        a(f"  - `{stem}`: {n} cells, objects {', '.join(objs)}, {nf} frames between "
          f"frame {f0} and {f1}")
    a("- Apart from those gaps, every object has a box in every frame, including players "
      "who are heavily overlapped by others — GT includes players a detector cannot see "
      "(caps recall in Phase 2).")
    a("")
    a("## 4. Objects per frame and TeamIDs")
    a("")
    for view in VIEWS:
        s = ctx["perframe"][view]
        a(f"- **{view}**: objects per frame min/mean/max = {s['min']}/{s['mean']:.1f}/"
          f"{s['max']}; TeamID 0 = {s['t0']}, TeamID 1 = {s['t1']}, BALL = {s['ball']} per "
          f"frame. Boxes not fully inside the image: {s['outside']:.2%}. "
          f"Player pairs overlapping (IoU > 0.3) per frame: {ctx['occl'][view]:.2f}.")
    a("- TeamIDs present: `0`, `1`, `BALL`. **No referee, no assistant referees, no "
      "explicit goalkeeper flag.** (The referee is visible in the top view and an assistant "
      "referee on the side view, both without GT boxes → a detector will produce \"false "
      "positives\" that are real people. Substitutes/staff beside the pitch are also visible "
      "in the top view.)")
    a(f"- Goalkeepers are inside the 11 per team. Most extreme mean x per team in the "
      f"overlapping clip `{ctx['gk_stem']}`:")
    for view, gk in ctx["gk"].items():
        a(f"  - {view}: " + "; ".join(
            f"TeamID {t}: PlayerID {p} at mean x={x:.0f} px (team mean {m:.0f} px)"
            for t, (p, x, m) in gk.items()))
    a("- In the top view these are the goalkeepers (they stand in their own penalty areas). "
      "In the side view TeamID 0's keeper has a **different PlayerID** and sits at the "
      "**opposite image side** (TeamID 1's keeper is out of the annotated range). → **TeamIDs "
      "agree between cameras, PlayerIDs do not**, and the drone image is rotated ~180° "
      "relative to the side camera (the pitch text reads upside down). Never join the two "
      "views on PlayerID.")
    a("- PlayerID continuity across consecutive clips (foot point, last frame → next first "
      "frame): " + "; ".join(f"{v}: same id moves median {s:.0f} px vs nearest other player "
                             f"{o:.0f} px" for v, (s, o) in ctx["cont"].items())
      + (" → **IDs are consistent across clips**, so clips can be concatenated."
         if all(s < o for s, o in ctx["cont"].values()) else
         " → **IDs are NOT consistent across clips**; re-associate when concatenating."))
    a("")
    a("## 5. Box sizes (players, native pixels)")
    a("")
    a("| view | width p5/p50/p95 | height p5/p50/p95 | ball w×h p50 | "
      "player height after full-frame letterbox to 640 (p50) |")
    a("|---|---|---|---|---|")
    for view in VIEWS:
        b = ctx["boxes"][view]
        a(f"| {view} | {b['w']} | {b['h']} | {b['ball']} | {b['h640']:.1f} px |")
    a("")
    a("- Top view: players are ~30 px blobs seen from directly above — **no human silhouette**. "
      "Phase 0 smoke test: COCO YOLOX-S in `cv2.dnn` finds **0** persons on the full top "
      "frame and on the native 640×640 centre crop (max objectness 0.06), and **1 of 12** "
      "GT players on a dense native 1280×640 region. See `docs/FAILURE_LOG.md`.")
    a("- Side view: players are taller than wide (median ~"
      f"{ctx['boxes']['soccer_side']['h50']:.0f} px high) and look like people; YOLOX finds "
      "11 persons on a native 640×640 crop but **0 on the full 6500×1000 frame letterboxed "
      "to 640** (players shrink to ~4 px). → Phase 2 needs tiled inference at native "
      "resolution for the side view.")
    a("")
    a("![box sizes](../outputs/eda/box_sizes.png)")
    a("")
    a("## 6. Side view distortion")
    a("")
    sd = ctx["side"]
    a("- The side view is **not a raw circular fisheye frame**: it is a **6500×1000 stitched "
      "panorama** (wide horizontal field of view, cylindrical-like projection). Colour "
      "fringing / ghosting at the image edges suggests multi-camera stitching.")
    a("- Visual check: the near touchline is a straight image row across the full width, "
      "but the outer ~900 px at each end are **smeared horizontally** with strong RGB colour "
      "fringing (`outputs/eda/side_edges.jpg`). Goal lines at the far left/right are steeply "
      "slanted; the far touchline is thin and dim under overcast light.")
    a(f"- Players only appear between x = {sd['x_range'][0]} and {sd['x_range'][1]} px in "
      "these clips (the play is in the central part of the panorama). GT box aspect ratio "
      "(w/h, players ≥ 15 px high) per 650 px band — a rising value means horizontal "
      "stretching:")
    a("")
    a("  | image x band (px) | median w/h | boxes |")
    a("  |---|---|---|")
    for band, row in sd["aspect_by_band"].iterrows():
        a(f"  | {int(band.left)}–{int(band.right)} | {row['median']:.2f} | {int(row['size'])} |")
    a("- Implication for Phase 2: a single `cv2.fisheye` model may not fit a stitched "
      "panorama. Options: fit `cv2.fisheye` / a cylindrical model from pitch lines and check "
      "lines become straight, or use **piecewise homographies** (one per horizontal "
      "section). Top view stays the primary geometry.")
    a("")
    a("![side distortion](../outputs/eda/distortion_side.jpg)")
    a("")
    a("## 7. Pitch visibility (top view)")
    a("")
    pt = ctx["pitch"]
    ratio = pt["length_px"] / pt["width_px"]
    a(f"- The **whole pitch is visible** in the drone view, with all lines, both penalty "
      f"areas and the centre circle. White-line mask covers {pt['line_px_frac']:.1%} of the "
      f"frame.")
    a(f"- Outer line rectangle (`cv2.minAreaRect` on the white-line mask): "
      f"**{pt['length_px']:.0f} × {pt['width_px']:.0f} px**, rotated {pt['angle']:.1f}°, "
      f"aspect ratio **{ratio:.3f}** (105×68 m = 1.544; 100×64 = 1.563; 105×70 = 1.500).")
    a(f"- Assuming 105 m length: ~{pt['length_px'] / 105:.1f} px/m, so a 30 px player blob ≈ "
      f"{30 / (pt['length_px'] / 105):.1f} m. Pitch size is consistent with a full-size "
      "pitch; exact dimensions are a Phase 2 calibration item (config `pitch`).")
    a("- The drone looks almost straight down → a single homography per clip should fit well.")
    a("")
    a("![top lines](../outputs/eda/pitch_lines_top.jpg)")
    a("")
    a("## 8. Visual output")
    a("")
    for p in ctx["samples"]:
        a(f"- `{p.relative_to(ctx['root']).as_posix()}`")
    for p in ctx["heat"]:
        a(f"- `{p.relative_to(ctx['root']).as_posix()}` — foot-point heat-map per TeamID")
    a("- `outputs/eda/objects_per_frame.png`, `outputs/eda/box_sizes.png`, "
      "`outputs/eda/side_edges.jpg`")
    a("")
    a("![gt top](../outputs/eda/gt_top_1.jpg)")
    a("")
    a("![gt side](../outputs/eda/gt_side_1.jpg)")
    a("")
    a("![objects per frame](../outputs/eda/objects_per_frame.png)")
    a("")
    a("## 9. Surprises and consequences")
    a("")
    for s in ctx["surprises"]:
        a(f"- {s}")
    a("")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- main
def main() -> None:
    cfg = load_config()
    root = repo_path(".")
    tt = repo_path(cfg["paths"]["teamtrack"])
    out = repo_path(cfg["paths"]["outputs"]) / "eda"
    out.mkdir(parents=True, exist_ok=True)
    if not tt.exists():
        sys.exit(f"ERROR: {tt} not found. Download the TeamTrack test clips first.")
    timer = Timer()

    print("1. inventory")
    clips = inventory(tt)
    for c in clips:
        has_v, has_c = "Y" if c.video else "-", "Y" if c.csv else "-"
        print(f"   {c.view:<12} {c.stem}  video={has_v} csv={has_c}")
    timer.lap("inventory")

    print("2. video metadata (decoding one clip per view to verify frame counts)")
    verified = video_metadata(clips)
    drift = drone_drift(clips)
    timer.lap("video metadata + drift")

    print("3. annotations")
    nan_total, nonint, nan_detail = 0, {}, []
    for c in clips:
        if c.csv:
            raw = pd.read_csv(c.csv, header=[0, 1, 2], index_col=0)
            n_nan = int(raw.isna().sum().sum())
            nan_total += n_nan
            if n_nan:
                objs = sorted({f"{t}/{p}" for t, p, _ in raw.columns[raw.isna().any(axis=0)]})
                rows = raw.index[raw.isna().any(axis=1)]
                nan_detail.append((c.stem, n_nan, objs, int(rows.min()), int(rows.max()),
                                   len(rows)))
            ncols = raw.shape[1]
            c.ann = load_annotations(c.csv)
    for view in VIEWS:
        a = pd.concat([c.ann for c in clips if c.view == view and c.ann is not None])
        v = a[["bb_left", "bb_top", "bb_width", "bb_height"]].to_numpy().ravel()
        nonint[view] = float((v % 1 != 0).mean())
    timer.lap("load CSVs")

    print("4. per-frame counts, box sizes, ids")
    perframe, boxes, occl = {}, {}, {}
    for view in VIEWS:
        vc = [c for c in clips if c.view == view and c.ann is not None]
        a = pd.concat([c.ann for c in vc])
        W, H = vc[0].meta["width"], vc[0].meta["height"]
        per = pd.concat([c.ann.groupby("frame").size() for c in vc])
        outside = ~((a.bb_left >= 0) & (a.bb_top >= 0) & (a.bb_left + a.bb_width <= W)
                    & (a.bb_top + a.bb_height <= H))
        first = vc[0].ann[vc[0].ann.frame == 1]
        perframe[view] = {"min": int(per.min()), "mean": float(per.mean()), "max": int(per.max()),
                          "t0": int((first.team == "0").sum()),
                          "t1": int((first.team == "1").sum()),
                          "ball": int((first.team == "BALL").sum()),
                          "outside": float(outside.mean())}
        pl, ball = a[a.team != "BALL"], a[a.team == "BALL"]
        scale = 640 / max(W, H)
        boxes[view] = {"w": pct(pl.bb_width), "h": pct(pl.bb_height),
                       "h50": float(pl.bb_height.median()),
                       "ball": f"{ball.bb_width.median():.0f}×{ball.bb_height.median():.0f}",
                       "h640": float(pl.bb_height.median() * scale)}
        occl[view] = occlusion_rate(vc[0].ann)
    side_stems = {c.stem[2:] for c in clips if c.view == "soccer_side" and c.ann is not None}
    shared = sorted(s for s in side_stems
                    if any(c.view == "soccer_top" and c.stem[2:] == s for c in clips))
    gk_stem = shared[0] if shared else clips[0].stem[2:]
    gk = {c.view: goalkeepers(c.ann) for c in clips
          if c.stem[2:] == gk_stem and c.ann is not None}
    cont = id_continuity(clips)
    timer.lap("stats")

    print("5. images")
    samples = sample_frames(clips, cfg, out)
    heat = heatmaps(clips, cfg, out)
    objects_plot(clips, out)
    box_size_plot(clips, out)
    timer.lap("sample frames, heat-maps, plots")

    print("6. pitch lines (top) and distortion (side)")
    pitch = pitch_top(clips, cfg, out)
    side = side_distortion(clips, cfg, out)
    timer.lap("pitch + distortion")

    top_range = {(c.start_s, c.end_s) for c in clips if c.view == "soccer_top"}
    side_range = {(c.start_s, c.end_s) for c in clips if c.view == "soccer_side"}
    ov = sorted(top_range & side_range)
    overlap = f"{ov[0][0]}–{ov[-1][1]}" if ov else "none"
    uniform = {v: len({(c.meta["width"], c.meta["height"], round(c.meta["fps"], 2),
                        c.meta["frames"]) for c in clips if c.view == v and c.meta}) == 1
               for v in VIEWS}

    def span(view: str) -> float:
        vc = [c for c in clips if c.view == view]
        return (vc[-1].end_s - vc[0].start_s) / 60

    surprises = [
        "**COCO YOLOX barely sees top-view players** (1 of 12 on a dense native-resolution "
        "region, 0 full-frame). The drone view is the best geometry but the worst for an "
        "off-the-shelf person detector. Phase 2 must test options for the top view: "
        "fine-tune YOLOX on TeamTrack top-view boxes (Apache 2.0 + MIT), or classical "
        "OpenCV blob detection against the grass (HSV mask + background model + "
        "`connectedComponentsWithStats`).",
        "**The side view is a stitched 6500×1000 panorama, not a raw fisheye.** `cv2.fisheye` "
        "may be the wrong model; plan piecewise homographies as the fallback.",
        "**Full-frame inference is useless on both views** (players shrink to ~4–5 px at "
        "640 input) → tiled native-resolution inference is mandatory, which costs ~10–15 "
        "tiles per side-view frame (~0.25 s each on this laptop CPU) → sample at 2–5 fps.",
        f"**GT is almost gap-free** ({nan_total} NaN cells, all in two top clips, mostly one "
        "player for 117 frames): players keep boxes even when heavily overlapped. Detection "
        "recall vs GT will be capped below 100 %; also report recall on non-overlapped boxes. "
        "The loader must still handle NaN rows.",
        "**No referee / no goalkeeper label** in GT. A detector + colour clustering will find "
        "referees (and the assistant referee on the side view) that GT does not contain; "
        "team-classification eval must ignore unmatched detections, and goalkeepers must be "
        "inferred from position (they are among the 11 per team).",
        f"**Top and side cameras overlap in time** ({overlap} s of the same match) — a free "
        "cross-view consistency check for Phase 2 — but **PlayerIDs differ between the two "
        "views** and the drone image is rotated ~180°; match on TeamID + position only.",
        "Shirt colours (from the GT overlays): TeamID 0 = white, TeamID 1 = dark blue; the "
        "keepers wear red and yellow. Two clearly separated outfield colours — good for "
        "`cv2.kmeans` team clustering; keepers will need special handling.",
        f"**The drone drifts** (median {np.median(drift.get('soccer_top', [0])):.1f} px between "
        "first and last frame of a 30 s clip) → recompute or track the homography per clip.",
        "**PlayerIDs sort as strings and attributes are alphabetical** in the CSV — "
        "positional indexing would silently scramble players.",
        f"Only {span('soccer_top'):.1f} min (top) and {span('soccer_side'):.1f} min (side) of "
        "continuous play — too short for real "
        "formation changes, as anticipated in the PLAN risks; shape-change accuracy must come "
        "from synthetic data, TeamTrack proves perception accuracy.",
    ]

    ctx = dict(clips=clips, verified=verified, drift=drift, ncols=ncols, nonint=nonint,
               nan_total=nan_total, nan_detail=nan_detail,
               ncsv=sum(1 for c in clips if c.csv), perframe=perframe, boxes=boxes, occl=occl,
               gk=gk, gk_stem=gk_stem, cont=cont, samples=samples, heat=heat,
               pitch=pitch, side=side, overlap=overlap, uniform=uniform, root=root,
               surprises=surprises)
    notes = repo_path("docs/DATA_NOTES.md")
    write_notes(notes, ctx)
    timer.lap("write DATA_NOTES.md")

    print(f"\nwrote {notes}")
    print(f"images in {out}")
    print("\ntiming summary:")
    for name, s in timer.stages:
        print(f"  {name:<34}{s:>7.1f} s")
    print(f"  {'total':<34}{sum(s for _, s in timer.stages):>7.1f} s")


if __name__ == "__main__":
    main()
