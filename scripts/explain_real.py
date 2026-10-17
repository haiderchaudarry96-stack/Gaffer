"""Build step 7, task 1: new explanations for the 14 real-footage candidates; nothing else runs.

The step-6 traces (`outputs/agent_video_final`: drone eval2 + eval and side eval2;
`outputs/agent_video_taskE`: the 900-1260 s demonstration window) are replayed through the
Toolbox, per arm: `check_frame_quality` returns the stored result (no OpenCV), `reanalyse_window`
comes from the disk cache (an uncached run raises: no new OpenCV), guard blocks and
`record_decision` are replayed with the stored arguments. Asserted per candidate and arm: the
config fingerprint is the frozen one, every replayed rules verdict and the decision equal the
stored ones, and both arms decide the same. Then the explanation step (agent/explain.py) runs:
Nova for the llm arm (run cost cap `--max-cost-usd`, default 0.50 USD), the template for the
rules arm. Nothing is decided again; no alert or evidence is written (see `--render`).

    py scripts\\explain_real.py --dev 45     # prompt check first: dev seed 45 (synthetic)
    py scripts\\explain_real.py              # the 14 real candidates, once
    py scripts\\explain_real.py --only side_eval2:evt_001   # re-explain one candidate

Output: `outputs/agent_video_step7/explanations.json` (before / after per candidate, the
automatic check on both, cost) and a before/after table in the log.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_agent import fingerprint  # noqa: E402
from run_agent_video import SETS  # noqa: E402

from gaffer.agent import explain  # noqa: E402
from gaffer.agent.alerts import AlertStore  # noqa: E402
from gaffer.agent.context import MatchContext  # noqa: E402
from gaffer.agent.explain import Explainer  # noqa: E402
from gaffer.agent.loop import (  # noqa: E402
    AgentRunner,
    RateLimiter,
    TraceWriter,
    _synthetic_context,
)
from gaffer.agent.tools import CandidateState, Toolbox, clock  # noqa: E402
from gaffer.agent.verify import Geometry  # noqa: E402
from gaffer.agent.vision import VideoBackend  # noqa: E402
from gaffer.config import load_config, repo_path  # noqa: E402
from gaffer.schema import load_match_state  # noqa: E402
from gaffer.tactics.common import TacticsConfig  # noqa: E402

FROZEN = "ca4ff9bbf7b01c6c"
GROUPS = (("outputs/agent_video_final", ("eval2", "eval", "side_eval2")),
          ("outputs/agent_video_taskE", ("w900",)))
OUT = "outputs/agent_video_step7"


def _no_opencv(*_a: Any, **_k: Any) -> Any:
    raise RuntimeError("replay: an uncached re-analysis would run OpenCV - not allowed here")


class ReplayToolbox(Toolbox):
    """The Toolbox with `check_frame_quality` served from the stored step-6 result."""

    next_quality: dict[str, Any] | None = None

    def _video_quality(self, st: CandidateState, lo: float, hi: float):
        s = self.next_quality
        if s is None or [round(float(v), 1) for v in s["window"]] != [round(lo, 1),
                                                                         round(hi, 1)]:
            raise RuntimeError(f"replay: no stored quality result for {lo:.0f}-{hi:.0f} s")
        shift = s["camera_shift_px_per_s_max"]
        st.geometry = Geometry(float(s["homography_ok_share"]),
                               math.inf if isinstance(shift, str) else float(shift),
                               float(s["zoom_change_max"]), bool(s["camera_cut"]))
        st.looked = True
        self._update_verdict(st)
        out = {k: v for k, v in s.items() if k not in ("rules", "ok")}
        out["ok"] = st.verdict.verdict != "refuse"
        out["rules"] = self.rules_block(st)
        st.quality = {k: v for k, v in out.items() if k != "rules"}
        self.next_quality = None
        return out, (lo, hi)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return ([json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
            if path.exists() else [])


def replay(tb: ReplayToolbox, ctx: MatchContext, row: dict[str, Any],
           lines: list[dict[str, Any]]) -> CandidateState:
    """The stored calls of one candidate up to its decision; asserts every ref, error and
    rules verdict, then the decision, against the stored trace."""
    st = tb.new_state(ctx.candidate(row["event_id"]))
    tid = row["trace_id"]
    for x in lines:
        kind = x.get("kind")
        if kind == "guard_block":
            res = tb.reject(st, x["tool"], x.get("message") or "")
            st.exhausted = True  # the loop's vision-budget block marks the evidence as spent
        elif kind == "tool_call":
            if x["tool"] in ("render_evidence", "propose_alert"):
                break
            if x["tool"] == "check_frame_quality" and x.get("result_summary", {}).get("window"):
                tb.next_quality = x["result_summary"]
            if x["tool"] == "record_decision" and x.get("actor") == "rules":
                st.exhausted = True  # the rules policy decides with what it has
            res = tb.run(st, x["tool"], x["args"])
        else:
            continue
        assert res["ref"] == x["ref"], (tid, x["step"], res["ref"], x["ref"])
        assert (res.get("error") or None) == (x.get("error") or None), (tid, x["step"], res)
        stored = (x.get("result_summary") or {}).get("rules")
        if stored and "rules" in res:
            for k in ("verdict", "failed", "missing"):
                assert res["rules"][k] == stored[k], (tid, x["step"], k, res["rules"], stored)
        if x.get("tool") == "record_decision" and "error" not in res:
            break
    dec = next(x for x in lines if x.get("kind") == "decision")
    assert st.decision == dec["decision"] == row["decision"], (tid, st.decision, dec["decision"])
    assert st.verdict.as_dict() == dec["verdict"], (tid, st.verdict.as_dict(), dec["verdict"])
    return st


def _table(items: list[dict[str, Any]]) -> str:
    out = ["| set | event | change | onset | decision | cause | before (step 6, Nova) | "
           "auto-check on before | after | source | flags on Nova's new text |",
           "|" + "---|" * 11]
    for x in items:
        out.append(f"| {x['set']} | {x['event_id']} | {x['change']} | {x['clock']} | "
                   f"{x['decision']} | {x['cause']} | {x['before']} | "
                   f"{'; '.join(x['before_flags']) or 'none'} | {x['after']} | {x['source']} | "
                   f"{'; '.join(x['after_raw_flags']) or 'none'} |")
    return "\n".join(out)


def run_real(cfg: dict[str, Any], max_cost: float, only: set[str] | None) -> int:
    from gaffer.llm.bedrock_client import BedrockClient, BedrockError

    out_dir = repo_path(OUT)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "explanations.json"
    prev = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    kept = {(x["set"], x["event_id"]): x for x in prev.get("candidates", [])}
    try:
        client = BedrockClient(cfg)
    except BedrockError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    limiter = RateLimiter(int(cfg["agent"]["llm"]["max_rpm"]))
    spent = float(prev.get("llm", {}).get("cost_usd", 0.0)) if only else 0.0
    nova = Explainer(cfg, llm=client, limiter=limiter, max_cost_usd=max_cost - spent)
    rows_out: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    for group, sets in GROUPS:
        g = repo_path(group)
        rows = {arm: _jsonl(g / ("rows_llm.jsonl" if arm == "llm" else "rows.jsonl"))
                for arm in ("llm", "rules")}
        traces = {arm: _jsonl(g / f"trace_{arm}.jsonl") for arm in ("llm", "rules")}
        for set_name in sets:
            path, view = SETS[set_name]
            m = load_match_state(repo_path(path))
            ctx = MatchContext(m, cfg, view=view)
            vb = VideoBackend.for_match_file(path, m, view, cfg, runner=_no_opencv)
            for row in [r for r in rows["llm"] if r["set"] == set_name]:
                key = f"{set_name}:{row['event_id']}"
                if only and key not in only:
                    continue
                states = {}
                for arm in ("llm", "rules"):
                    r = row if arm == "llm" else next(
                        x for x in rows["rules"] if x["set"] == set_name
                        and x["event_id"] == row["event_id"])
                    lines = [x for x in traces[arm] if x.get("trace_id") == r["trace_id"]]
                    tb = ReplayToolbox(ctx, AlertStore(out_dir / "alerts_replay.jsonl"),
                                       out_dir / "evidence", video=vb)
                    states[arm] = (replay(tb, ctx, r, lines), tb, r)
                (st, tb, r), (st_r, tb_r, _) = states["llm"], states["rules"]
                assert st.decision == st_r.decision, (key, st.decision, st_r.decision)
                f = explain.facts(tb, st)
                e = nova.explain(f, purpose=f"explain_real:{key}")
                tpl_rules = explain.template(explain.facts(tb_r, st_r))
                before = r.get("explanation") or ""
                c = ctx.candidate(row["event_id"])
                item = {
                    "set": set_name, "event_id": c.id, "team": tb.team_name(c.team),
                    "change": f"{c.from_} -> {c.to}", "clock": clock(c.t),
                    "decision": st.decision, "decision_rules_arm": st_r.decision,
                    "verdict": st.verdict.as_dict(), "cause": f["cause"],
                    "reason_stored": r["reason"], "reason_now": st.reason,
                    "before": before, "before_flags": explain.check(before, f, cfg),
                    "after": e.text, "source": e.source, "after_raw": e.raw,
                    "after_raw_flags": e.flags, "template_rules_arm": tpl_rules,
                    "llm": e.llm, "cost_usd": round(e.cost_usd, 6), "facts": f,
                }
                kept[(set_name, c.id)] = item
                rows_out.append(item)
                print(f"{key} {item['change']} @{item['clock']}: {st.decision} ({f['cause']}) "
                      f"| {e.source}{' FLAGGED ' + str(e.flags) if e.flags else ''}\n"
                      f"    before: {before}\n    after : {e.text}"
                      + (f"\n    raw   : {e.raw}" if e.raw else ""), flush=True)
    items = sorted(kept.values(), key=lambda x: ([s for _, ss in GROUPS for s in ss]
                                                  .index(x["set"]), x["event_id"]))
    llm_total = {"calls": nova.calls + (prev.get("llm", {}).get("calls", 0) if only else 0),
                 "cost_usd": round(spent + nova.cost, 5),
                 "tokens_in": nova.tokens["in"] + (prev.get("llm", {}).get("tokens_in", 0)
                                                   if only else 0),
                 "tokens_out": nova.tokens["out"] + (prev.get("llm", {}).get("tokens_out", 0)
                                                     if only else 0)}
    summary = {
        "candidates": len(items),
        "decisions_identical_to_step6": True,  # asserted in replay() for both arms
        "fingerprint": fingerprint(cfg),
        "before_auto_flagged": sum(bool(x["before_flags"]) for x in items),
        "after_sources": {s: sum(x["source"] == s for x in items) for s in ("agent",
                                                                             "template")},
        # a Nova text existed and the check replaced it (an LLM error is not a flagged text)
        "nova_texts_flagged": sum(x["after_raw"] is not None for x in items),
        "nova_unreachable": sum(any(f.startswith(("llm error", "explanation budget"))
                                    for f in x["after_raw_flags"]) for x in items),
    }
    report = {"summary": summary, "llm": llm_total, "candidates": items,
              "wall_s": round(time.perf_counter() - t0, 1)}
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("\n" + _table(items) + f"\n\n{json.dumps(summary)}\nLLM: {json.dumps(llm_total)}"
          f"\n-> {out_path}")
    return 0


def _panel_strip(img: np.ndarray, cfg: dict[str, Any]) -> np.ndarray:
    """The before / after shape panels at the bottom of an evidence image (rendered by
    `Toolbox.render_shapes`, scaled to the image width)."""
    tc = TacticsConfig.from_config(cfg)
    panel_w, panel_h = int((tc.pitch_length_m + 6) * 6), int((tc.pitch_width_m + 6) * 6)
    k = img.shape[1] / (2 * panel_w + 8)
    return img[img.shape[0] - int(round((30 + panel_h) * k)):]


def run_render(cfg: dict[str, Any]) -> int:
    """Task 2: evidence image + pending alert of every confirmed real candidate with the
    step-7 shape panels and the step-7 explanation (no LLM call, no re-analysis; one video
    frame is decoded and drawn on), plus a before/after crop of the shape panels."""
    out_dir = repo_path(OUT)
    data = json.loads((out_dir / "explanations.json").read_text(encoding="utf-8"))
    alerts = out_dir / "alerts_llm.jsonl"
    if alerts.exists():
        alerts.unlink()  # written only by this mode: the alerts of the latest render
    store = AlertStore(alerts)
    for item in data["candidates"]:
        if item["decision"] != "confirmed":
            continue
        set_name = item["set"]
        group = next(g for g, ss in GROUPS if set_name in ss)
        path, view = SETS[set_name]
        m = load_match_state(repo_path(path))
        ctx = MatchContext(m, cfg, view=view)
        vb = VideoBackend.for_match_file(path, m, view, cfg, runner=_no_opencv)
        g = repo_path(group)
        row = next(r for r in _jsonl(g / "rows_llm.jsonl")
                   if r["set"] == set_name and r["event_id"] == item["event_id"])
        lines = [x for x in _jsonl(g / "trace_llm.jsonl") if x.get("trace_id") == row["trace_id"]]
        tb = ReplayToolbox(ctx, store, out_dir / "evidence", video=vb)
        st = replay(tb, ctx, row, lines)
        st.explanation, st.explanation_source = item["after"], item["source"]
        st.explanation_flags = list(item["after_raw_flags"])
        stored = {x["tool"]: x["args"] for x in lines if x.get("kind") == "tool_call"
                  and x["tool"] in ("render_evidence", "propose_alert")}
        img = tb.run(st, "render_evidence", stored["render_evidence"])
        assert "error" not in img, img
        al = tb.run(st, "propose_alert", stored["propose_alert"])
        assert "error" not in al, al
        old = cv2.imread(str(repo_path(row["evidence_image"])))
        new = cv2.imread(str(repo_path(img["image"])))
        strips = []
        for label, im in ((f"BEFORE (step 6): {row['evidence_image']}", old),
                          (f"AFTER (step 7): {img['image']}", new)):
            s = _panel_strip(im, cfg)
            bar = np.full((34, s.shape[1], 3), (40, 40, 40), np.uint8)
            cv2.putText(bar, label, (8, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1,
                        cv2.LINE_AA)
            strips.append(np.vstack([bar, s]))
        cmp_path = out_dir / f"{item['event_id']}_{set_name}_panels_before_after.jpg"
        cv2.imwrite(str(cmp_path), np.vstack(strips), [cv2.IMWRITE_JPEG_QUALITY, 90])
        print(f"{set_name}:{item['event_id']} -> {img['image']} ({img['bytes']} bytes, frame "
              f"{img.get('clock')})\n  shows: {img['shows']}\n  alert {al['alert_id']} "
              f"{al['status']}\n  panels before/after -> {cmp_path}", flush=True)
    for a in store.all().values():
        print(json.dumps(a.model_dump(), indent=2))
    return 0


def run_dev(cfg: dict[str, Any], seed: int, max_cost: float) -> int:
    """Prompt check on a dev seed (synthetic backend, rules decide, Nova words): the only data
    the explanation prompt is developed on. Spends a few cents."""
    from gaffer.llm.bedrock_client import BedrockClient, BedrockError

    if seed in set(cfg["eval"]["synthetic"]["heldout_seeds_2"]) | set(
            cfg["eval"]["synthetic"].get("heldout_seeds", [])):
        print("ERROR: held-out seeds are not for prompt work", file=sys.stderr)
        return 2
    try:
        client = BedrockClient(cfg)
    except BedrockError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    ctx = _synthetic_context(seed, cfg)
    out_dir = repo_path(f"{OUT}/dev_seed{seed}")
    out_dir.mkdir(parents=True, exist_ok=True)
    limiter = RateLimiter(int(cfg["agent"]["llm"]["max_rpm"]))
    nova = Explainer(cfg, llm=client, limiter=limiter, max_cost_usd=max_cost)
    tb = Toolbox(ctx, AlertStore(out_dir / "alerts.jsonl"), out_dir / "evidence")
    runner = AgentRunner(ctx, tb, arm="rules", trace=TraceWriter(out_dir / "trace.jsonl"),
                         run_id=f"explain_dev{seed}", explainer=nova, limiter=limiter)
    outs = runner.run()
    for o in outs:
        print(f"{o.event_id} {o.decision:9s} {o.explanation_source:8s} {o.reason}\n"
              f"    {o.explanation}"
              + (f"\n    flags: {o.explanation_flags}" if o.explanation_flags else ""))
    raw = [x for x in _jsonl(out_dir / "trace.jsonl") if x.get("kind") == "explanation"
           and x.get("replaced_text")]
    for x in raw:
        print(f"replaced {x['event_id']}: {x['replaced_text']}\n    flags: {x['flags']}")
    kept = sum(o.explanation_source == "agent" for o in outs)
    print(f"\n{len(outs)} candidates, Nova texts kept {kept}, replaced {len(raw)}; "
          f"{json.dumps(nova.stats())}")
    return 0


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dev", type=int, default=None, help="prompt check on this dev seed")
    ap.add_argument("--max-cost-usd", type=float, default=0.50)
    ap.add_argument("--only", default=None, help="comma-separated SET:EVENT keys")
    ap.add_argument("--render", action="store_true",
                    help="evidence + pending alert of the confirmed candidates (task 2)")
    args = ap.parse_args(argv)
    fp = fingerprint(cfg)
    if fp != FROZEN:
        print(f"ERROR: decision config changed ({fp} != frozen {FROZEN})", file=sys.stderr)
        return 2
    if args.dev is not None:
        return run_dev(cfg, args.dev, args.max_cost_usd)
    if args.render:
        return run_render(cfg)
    return run_real(cfg, args.max_cost_usd, set(args.only.split(",")) if args.only else None)


if __name__ == "__main__":
    raise SystemExit(main())
