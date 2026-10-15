"""The agent loop: perceive -> decide -> act per candidate (docs/AGENT_DESIGN.md §3, §6).

One short Bedrock conversation per candidate, in time order. Code builds the first message
(the candidate card); every turn is a tool call (`tool_choice=any`); the rules verdict computed
by code bounds what the model may record (`tools.Toolbox`). The loop adds the guard: step and
vision limits per candidate, repeated / malformed calls, nudges, per-match and per-run budgets,
a client-side rate limiter, and a deterministic **rules fallback** that finishes any candidate
the model cannot (quota exhausted, looping, step limit). The `rules` arm runs the same fallback
policy for every candidate: same tools, fixed order, no LLM.

Logs: `outputs/agent_trace.jsonl` (one line per step), alerts in `outputs/alerts.jsonl`
(pending until the coach decides), verified timeline next to the match.

CLI:
    py -m gaffer.agent.loop --match outputs\\match_state.json --arm rules
    py -m gaffer.agent.loop --synthetic-seed 45 --arm llm --max-candidates 3 --max-calls 30
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from gaffer.agent.alerts import AlertStore
from gaffer.agent.context import MatchContext
from gaffer.agent.tools import VISION_TOOLS, CandidateState, Toolbox, clock, tool_specs
from gaffer.agent.verify import DECISION_OF, Candidate
from gaffer.config import load_config, repo_path
from gaffer.llm.bedrock_client import (
    BedrockCallError,
    BedrockError,
    BedrockModelAccessError,
    BedrockThrottlingError,
    ChatResult,
    user_message,
)
from gaffer.schema import ContractError, Verification, load_match_state, parse_match_state

SYSTEM_PROMPT = """You verify candidate formation changes for a football coach. A tactics engine \
proposed the candidate; your job is to check it with tools before anyone is alerted.

How it works:
- The first message is the candidate card. "rules" shows a verdict computed by code from the \
evidence so far: need_more, confirm, reject, uncertain or refuse. Every vision tool result \
updates it.
- If the verdict is need_more, gather evidence: check_frame_quality and/or reanalyse_window over \
the required re-analysis span, with event_id set. Do not record a decision while it is need_more.
- Then call record_decision with a decision the verdict allows (confirm -> confirmed or \
uncertain; reject -> rejected; uncertain/refuse -> uncertain or rejected), a short reason with \
numbers taken from tool results, and citations of the refs you used, e.g. [{"ref": "R2"}].
- After record_decision(confirmed): call render_evidence, then propose_alert. Title <= 80 \
characters; explanation <= 280 characters, plain words for a coach, citing refs like [R2]; \
suggestion <= 160 characters, one practical idea.

Rules: one tool call per turn. Never state a fact that is not in a tool result or the card. \
Use the mm:ss clocks given in results. If something is listed as unavailable (ball, possession, \
pressing), do not mention it. Prefer uncertain to a guess."""

NUDGE = ("Call a tool now. If the rules verdict is need_more, gather evidence with a vision tool; "
         "otherwise call record_decision.")


class LLM(Protocol):
    def chat(self, messages: list[dict[str, Any]], system: str | None = ...,
             tools: list[dict[str, Any]] | None = ..., tool_choice: str | None = ...,
             model_id: str | None = ..., max_tokens: int | None = ...,
             temperature: float | None = ..., purpose: str = ...) -> ChatResult: ...


class BudgetExceeded(RuntimeError):
    """A per-match or per-run cap would be exceeded by the next LLM call."""


@dataclass
class Budget:
    """LLM calls / tokens / cost, per match and per run (the spike's hard caps)."""

    prices: dict[str, list[float]]
    max_calls_match: int
    max_tokens_match: int
    max_cost_match: float
    max_calls_run: int | None = None
    max_cost_run: float | None = None
    max_tokens_out: int = 400
    run_calls: int = 0
    run_cost: float = 0.0
    run_tokens: Counter = field(default_factory=Counter)
    calls: int = 0
    tokens: Counter = field(default_factory=Counter)
    cost: float = 0.0
    last_input: int = 3000

    def new_match(self) -> None:
        self.calls, self.tokens, self.cost = 0, Counter(), 0.0

    def price(self, model: str) -> tuple[float, float]:
        p = self.prices.get(model)
        if p is None:
            raise BudgetExceeded(f"no price configured for model {model!r} "
                                 "(agent.llm.prices_per_1k)")
        return float(p[0]), float(p[1])

    def check_next(self, model: str) -> None:
        """Raise before a call that could break a cap (worst case: last input + 1 k tokens in,
        `max_tokens_out` out)."""
        pin, pout = self.price(model)
        est = (self.last_input + 1000) / 1000 * pin + self.max_tokens_out / 1000 * pout
        if self.calls + 1 > self.max_calls_match:
            raise BudgetExceeded(f"match LLM-call cap {self.max_calls_match} reached")
        if self.tokens["total"] + self.last_input + 1000 > self.max_tokens_match:
            raise BudgetExceeded(f"match token cap {self.max_tokens_match} reached")
        if self.cost + est > self.max_cost_match:
            raise BudgetExceeded(f"match cost cap ${self.max_cost_match} reached")
        if self.max_calls_run is not None and self.run_calls + 1 > self.max_calls_run:
            raise BudgetExceeded(f"run LLM-call cap {self.max_calls_run} reached")
        if self.max_cost_run is not None and self.run_cost + est > self.max_cost_run:
            raise BudgetExceeded(f"run cost cap ${self.max_cost_run} reached")

    def add(self, model: str, usage: dict[str, int]) -> float:
        pin, pout = self.price(model)
        tin, tout = int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
        cost = tin / 1000 * pin + tout / 1000 * pout
        self.calls += 1
        self.run_calls += 1
        self.cost += cost
        self.run_cost += cost
        for c in (self.tokens, self.run_tokens):
            c["in"] += tin
            c["out"] += tout
            c["total"] += tin + tout
        self.last_input = max(tin, 1000)
        return cost


class RateLimiter:
    """Client-side token bucket: at most `rpm` calls in any 60 s (account quota: 20 RPM)."""

    def __init__(self, rpm: int, clock_fn: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.rpm, self.clock, self.sleep = int(rpm), clock_fn, sleep
        self.stamps: list[float] = []
        self.waited_s = 0.0

    def wait(self) -> None:
        now = self.clock()
        self.stamps = [s for s in self.stamps if now - s < 60.0]
        if len(self.stamps) >= self.rpm:
            delay = 60.0 - (now - self.stamps[0]) + 0.05
            self.sleep(delay)
            self.waited_s += delay
            now = self.clock()
            self.stamps = [s for s in self.stamps if now - s < 60.0]
        self.stamps.append(now)


class TraceWriter:
    """Appends one JSON line per agent step to `outputs/agent_trace.jsonl`."""

    def __init__(self, path: str | Path) -> None:
        self.path = repo_path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: dict[str, Any]) -> None:
        record = {"ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), **record}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")


@dataclass
class Outcome:
    """How one candidate ended."""

    event_id: str
    decision: str
    decided_by: str
    reason: str
    verdict: str
    llm_calls: int = 0
    tool_calls: list[str] = field(default_factory=list)
    guard_blocks: int = 0
    invalid_calls: int = 0
    fallback: str | None = None
    alert_id: str | None = None
    evidence_image: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    llm_s: float = 0.0
    tool_s: float = 0.0
    trace_id: str = ""


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    """Trace view of a tool result: what the model saw, minus long arrays."""
    out = {}
    for k, v in result.items():
        if k == "ref":
            continue
        if isinstance(v, dict) and k == "labels":
            out[k] = {t: len(s.get("seq", [])) for t, s in v.items()}
        elif isinstance(v, list) and len(v) > 4:
            out[k] = f"[{len(v)} items]"
        else:
            out[k] = v
    return out


class AgentRunner:
    """Runs the `llm` or `rules` arm over the candidates of one match."""

    def __init__(self, ctx: MatchContext, toolbox: Toolbox, *, arm: str = "llm",
                 llm: LLM | None = None, budget: Budget | None = None,
                 limiter: RateLimiter | None = None, trace: TraceWriter | None = None,
                 run_id: str | None = None, cfg: dict[str, Any] | None = None) -> None:
        if arm not in ("llm", "rules"):
            raise ValueError("arm must be 'llm' or 'rules'")
        if arm == "llm" and llm is None:
            raise ValueError("the llm arm needs an LLM client")
        self.ctx, self.tb, self.arm, self.llm = ctx, toolbox, arm, llm
        self.cfg = cfg or ctx.cfg
        a = self.cfg["agent"]
        self.limits, self.lcfg = a["limits"], a["llm"]
        b = self.cfg["bedrock"]
        self.model = b["model_id"]
        self.fallback_model = b.get("fallback_model_id")
        self.budget = budget or make_budget(self.cfg)
        self.limiter = limiter or RateLimiter(int(self.lcfg["max_rpm"]))
        self.trace = trace or TraceWriter(a["outputs"]["trace"])
        self.run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        self.tool_choice = str(self.lcfg.get("tool_choice", "any"))
        self.tool_choice_any_ok: bool | None = None
        self.llm_down: str | None = None  # reason the LLM is unusable for the rest of the run
        self.throttled = 0
        self.specs = tool_specs()

    # ---------------------------------------------------------------- match
    def run(self, candidates: list[Candidate] | None = None) -> list[Outcome]:
        cands = list(self.ctx.candidates if candidates is None else candidates)
        self.budget.new_match()
        outcomes = []
        for i, c in enumerate(cands):
            use_llm = (self.arm == "llm" and self.llm_down is None
                       and i < int(self.limits["max_candidates_llm"]))
            outcomes.append(self.verify(c, use_llm=use_llm))
        self.trace.write({"run_id": self.run_id, "match_id": self.ctx.match.match_id,
                          "kind": "match_summary", "arm": self.arm,
                          "candidates": len(outcomes),
                          "decisions": dict(Counter(o.decision for o in outcomes)),
                          "decided_by": dict(Counter(o.decided_by for o in outcomes)),
                          "llm_calls": self.budget.calls, "tokens": dict(self.budget.tokens),
                          "cost_usd": round(self.budget.cost, 5),
                          "guard_blocks": sum(o.guard_blocks for o in outcomes),
                          "throttled": self.throttled, "llm_down": self.llm_down,
                          "tool_choice_any_ok": self.tool_choice_any_ok})
        return outcomes

    def trace_id(self, c: Candidate) -> str:
        return f"tr_{self.run_id}_{self.ctx.match.match_id}_{c.id}"

    # ---------------------------------------------------------------- candidate
    def verify(self, c: Candidate, use_llm: bool = True) -> Outcome:
        st = self.tb.new_state(c)
        out = Outcome(c.id, "", "", "", st.verdict.verdict, trace_id=self.trace_id(c))
        base = {"run_id": self.run_id, "trace_id": out.trace_id,
                "match_id": self.ctx.match.match_id, "event_id": c.id,
                "backend": self.ctx.backend, "arm": self.arm}
        self._step = 0
        self._last_ref = "R0"
        self.trace.write({**base, "step": 0, "actor": "code", "kind": "card",
                          "ref": "R0", "card": self.tb.card(st)})
        if use_llm:
            self._llm_loop(st, out, base)
        elif self.arm == "llm":
            out.fallback = f"rules ({self.llm_down or 'candidate cap'})"
        if not st.done:
            self._rules_policy(st, out, base)
        out.decision = st.decision or "uncertain"
        out.reason = st.reason
        out.verdict = st.verdict.verdict
        out.tool_calls = list(st.tool_calls)
        out.alert_id, out.evidence_image = st.alert_id, st.evidence_image
        out.decided_by = ("agent" if out.fallback is None and self.arm == "llm"
                          else "rules" if self.arm == "rules" else out.fallback)
        self.trace.write({**base, "step": self._step + 1, "actor": "code", "kind": "decision",
                          "decision": out.decision, "decided_by": out.decided_by,
                          "reason": out.reason, "citations": st.citations,
                          "verdict": st.verdict.as_dict(), "alert_id": out.alert_id,
                          "llm_calls": out.llm_calls, "guard_blocks": out.guard_blocks,
                          "tokens": {"in": out.tokens_in, "out": out.tokens_out},
                          "cost_usd": round(out.cost_usd, 5)})
        return out

    def _tool(self, st: CandidateState, out: Outcome, base: dict[str, Any], name: str,
              args: dict[str, Any], actor: str, llm_info: dict[str, Any] | None = None
              ) -> dict[str, Any]:
        t0 = time.perf_counter()
        res = self.tb.run(st, name, args)
        dt = time.perf_counter() - t0
        out.tool_s += dt
        self._step += 1
        err = res.get("error")
        if err == "not_allowed":
            out.guard_blocks += 1
        rec = {**base, "step": self._step, "actor": actor, "kind": "tool_call", "tool": name,
               "args": args, "ref": res.get("ref"), "prev_ref": self._last_ref,
               "result_summary": _summary(res), "duration_ms": round(dt * 1000, 1),
               "error": err}
        if llm_info:
            rec["llm"] = llm_info
        self.trace.write(rec)
        if res.get("ref"):
            self._last_ref = res["ref"]
        return res

    def _blocked(self, st: CandidateState, out: Outcome, base: dict[str, Any], name: str,
                 args: dict[str, Any], msg: str, llm_info: dict[str, Any] | None
                 ) -> dict[str, Any]:
        """A call the loop guard refuses without running it (logged, counted)."""
        res = self.tb.reject(st, name, msg)
        out.guard_blocks += 1
        self._step += 1
        rec = {**base, "step": self._step, "actor": "guard", "kind": "guard_block",
               "tool": name, "args": args, "ref": res["ref"], "prev_ref": self._last_ref,
               "error": "not_allowed", "message": msg}
        if llm_info:
            rec["llm"] = llm_info
        self.trace.write(rec)
        return res

    # ---------------------------------------------------------------- LLM conversation
    def _llm_loop(self, st: CandidateState, out: Outcome, base: dict[str, Any]) -> None:
        lim = self.limits
        msgs: list[dict[str, Any]] = [user_message(self.tb.card(st))]
        invalid_in_row = nudges = 0
        seen: Counter = Counter()
        cache: dict[str, dict[str, Any]] = {}
        while not st.done:
            if out.llm_calls >= int(lim["max_llm_calls_per_candidate"]):
                out.fallback = "guard: step limit"
                return
            if out.llm_calls >= int(lim["max_llm_calls_per_candidate"]) - 2:
                st.exhausted = True
            r = self._chat(msgs, out, base)
            if r is None:
                return
            msgs.append(r.message)
            llm_info = {"model_id": r.model_id, "in": r.usage.get("input_tokens", 0),
                        "out": r.usage.get("output_tokens", 0),
                        "latency_ms": round(r.latency_ms), "text": r.text[:300] or None}
            if not r.tool_uses:
                nudges += 1
                self._step += 1
                self.trace.write({**base, "step": self._step, "actor": "llm", "kind": "nudge",
                                  "llm": llm_info})
                if nudges > int(lim["max_nudges"]):
                    out.fallback = "guard: no tool call"
                    return
                msgs.append(user_message(NUDGE))
                continue
            results = []
            stop: str | None = None
            for tu in r.tool_uses:
                key = json.dumps([tu.name, tu.input], sort_keys=True, default=str)
                seen[key] += 1
                if seen[key] > int(lim["max_identical_calls"]):
                    stop = "guard: repeated call"
                    res = self._blocked(st, out, base, tu.name, tu.input,
                                        "identical call repeated again: stopping", llm_info)
                elif seen[key] > 1 and key in cache:
                    res = {**cache[key], "note": "repeated call, same result"}
                elif (tu.name in VISION_TOOLS and tu.name != "render_evidence"
                      and st.vision_calls >= int(lim["max_vision_calls_per_candidate"])):
                    st.exhausted = True
                    res = self._blocked(st, out, base, tu.name, tu.input,
                                        "vision budget for this candidate used: record a "
                                        "decision (uncertain is allowed)", llm_info)
                else:
                    res = self._tool(st, out, base, tu.name, tu.input, "llm", llm_info)
                    if "error" not in res:
                        cache[key] = res
                    if st.reanalyses >= int(lim["max_reanalyses_per_candidate"]):
                        st.exhausted = True
                llm_info = None  # tokens counted once per LLM call
                if res.get("error") in ("invalid_args", "unknown_tool"):
                    invalid_in_row += 1
                    out.invalid_calls += 1
                else:
                    invalid_in_row = 0
                results.append((tu.tool_use_id, res))
            msgs.append(_tool_results(results))
            if stop:
                out.fallback = stop
                return
            if invalid_in_row >= int(lim["max_invalid_in_a_row"]):
                out.fallback = "guard: malformed calls"
                return

    def _chat(self, msgs: list[dict[str, Any]], out: Outcome, base: dict[str, Any]
              ) -> ChatResult | None:
        """One rate-limited, budgeted LLM call; None (with `out.fallback` set) on failure."""
        assert self.llm is not None
        for _attempt in range(3):
            model = self.model
            try:
                self.budget.check_next(model)
            except BudgetExceeded as exc:
                self.llm_down = f"budget: {exc}"
                out.fallback = f"rules ({self.llm_down})"
                return None
            self.limiter.wait()
            t0 = time.perf_counter()
            try:
                r = self.llm.chat(msgs, system=SYSTEM_PROMPT, tools=self.specs,
                                  tool_choice=self.tool_choice, model_id=model,
                                  max_tokens=int(self.lcfg["max_tokens"]),
                                  temperature=float(self.lcfg["temperature"]),
                                  purpose=f"agent:{self.ctx.match.match_id}:{out.event_id}")
            except BedrockThrottlingError as exc:
                self.throttled += 1
                self._event(base, "throttled", str(exc).splitlines()[0])
                if exc.quota_exhausted:
                    self.llm_down = "quota exhausted"
                out.fallback = "rules (llm unavailable: throttled)"
                return None
            except BedrockModelAccessError as exc:
                if self.fallback_model and self.model != self.fallback_model:
                    self._event(base, "model_switch", f"{self.model} -> {self.fallback_model}: "
                                f"{str(exc).splitlines()[0]}")
                    self.model = self.fallback_model
                    continue
                self.llm_down = "model access"
                out.fallback = "rules (llm unavailable: model access)"
                return None
            except BedrockCallError as exc:
                low = str(exc).lower()
                if self.tool_choice == "any" and ("toolchoice" in low or "tool_choice" in low
                                                  or "tool choice" in low):
                    self.tool_choice, self.tool_choice_any_ok = "auto", False
                    self._event(base, "tool_choice_fallback", str(exc).splitlines()[0])
                    continue
                self._event(base, "llm_error", str(exc).splitlines()[0])
                out.fallback = "rules (llm error)"
                return None
            except BedrockError as exc:
                self.llm_down = type(exc).__name__
                out.fallback = f"rules (llm unavailable: {self.llm_down})"
                return None
            out.llm_s += time.perf_counter() - t0
            if self.tool_choice == "any" and self.tool_choice_any_ok is None:
                self.tool_choice_any_ok = True
            out.llm_calls += 1
            out.cost_usd += self.budget.add(r.model_id, r.usage)
            out.tokens_in += int(r.usage.get("input_tokens", 0))
            out.tokens_out += int(r.usage.get("output_tokens", 0))
            return r
        out.fallback = "rules (llm error)"
        return None

    def _event(self, base: dict[str, Any], kind: str, msg: str) -> None:
        self._step += 1
        self.trace.write({**base, "step": self._step, "actor": "code", "kind": kind,
                          "message": msg[:300]})

    # ---------------------------------------------------------------- rules policy
    def _rules_policy(self, st: CandidateState, out: Outcome, base: dict[str, Any]) -> None:
        """Deterministic completion (rules arm, and fallback after any LLM failure): quality
        check -> second look if needed -> decision the verdict implies -> evidence + alert."""
        c, actor = st.cand, "rules"
        a, b = self.ctx.required_span(c)
        if st.decision is None:
            if st.geometry is None:
                self._tool(st, out, base, "check_frame_quality",
                           {"start_s": a, "end_s": b, "why": "rules policy: quality first"},
                           actor)
            if st.verdict.verdict == "need_more" and not st.second_look \
                    and st.reanalyses < int(self.limits["max_reanalyses_per_candidate"]):
                fps = max(self._reanalysis_fps())
                self._tool(st, out, base, "reanalyse_window",
                           {"start_s": a, "end_s": b, "sample_fps": fps, "event_id": c.id,
                            "why": "rules policy: second look"}, actor)
            st.exhausted = True
            decision = DECISION_OF[st.verdict.verdict]
            refs = [r for r, info in st.refs.items() if info.ok
                    and info.tool in ("reanalyse_window", "check_frame_quality")][-1:] or ["R0"]
            res = self._tool(st, out, base, "record_decision",
                             {"event_id": c.id, "decision": decision,
                              "reason": st.verdict.reason[:200],
                              "citations": [{"ref": refs[0]}]}, actor)
            if "error" in res:  # e.g. a confirmation without a vision check: be cautious
                self._tool(st, out, base, "record_decision",
                           {"event_id": c.id, "decision": "uncertain",
                            "reason": f"rules policy could not confirm: {res['message']}"[:200],
                            "citations": [{"ref": "R0"}]}, actor)
        if st.decision == "confirmed" and st.alert_id is None:
            if st.evidence_image is None:
                self._tool(st, out, base, "render_evidence",
                           {"event_id": c.id, "why": "rules policy: evidence"}, actor)
            ref = next((r for r, info in st.refs.items() if info.ok and info.tool in
                        ("reanalyse_window", "check_frame_quality")), "R0")
            name = self.tb.team_name(c.team)
            self._tool(st, out, base, "propose_alert", {
                "event_id": c.id,
                "title": f"{name} changed shape: {c.from_} -> {c.to} ({clock(c.t)})"[:80],
                "explanation": (f"{st.verdict.reason} [{ref}].")[:280],
                "suggestion": "Check the evidence image and the clip around this moment."},
                actor)

    def _reanalysis_fps(self) -> list[int]:
        views = self.cfg["agent"]["views"]
        return list(views.get(self.ctx.view or "top", views["top"])["reanalysis_fps"])

    # ---------------------------------------------------------------- outputs
    def verified_timeline(self, outcomes: list[Outcome]) -> dict[str, Any]:
        """The contract timeline with `status` + `verification` filled for decided events."""
        by_id = {o.event_id: o for o in outcomes}
        tl = self.ctx.result.timeline.model_copy(deep=True)
        for e in tl.events:
            o = by_id.get(e.id)
            if o is None:
                continue
            e.status = o.decision
            e.verification = Verification(decided_by=o.decided_by, decision=o.decision,
                                          reason=o.reason or "", tool_calls=o.tool_calls,
                                          evidence_image=o.evidence_image, trace_id=o.trace_id)
        return json.loads(tl.to_json())


def _tool_results(results: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    content = []
    for tid, res in results:
        block: dict[str, Any] = {"toolUseId": tid, "content": [{"json": res}]}
        if "error" in res:
            block["status"] = "error"
        content.append({"toolResult": block})
    return {"role": "user", "content": content}


def make_budget(cfg: dict[str, Any], max_calls_run: int | None = None,
                max_cost_run: float | None = None) -> Budget:
    a = cfg["agent"]
    lim = a["limits"]
    return Budget(prices=dict(a["llm"]["prices_per_1k"]),
                  max_calls_match=int(lim["max_llm_calls_per_match"]),
                  max_tokens_match=int(lim["max_tokens_per_match"]),
                  max_cost_match=float(lim["max_cost_usd_per_match"]),
                  max_calls_run=max_calls_run, max_cost_run=max_cost_run,
                  max_tokens_out=int(a["llm"]["max_tokens"]))


# --------------------------------------------------------------------------- CLI


def _synthetic_context(seed: int, cfg: dict[str, Any]) -> MatchContext:
    from gaffer.synthetic import generate_match, match_001_schedule, random_schedule

    if seed == int(cfg["seed"]):
        path = repo_path("data/synthetic/match_001.json")
        if path.exists():
            return MatchContext(load_match_state(path), cfg)
        m, _ = generate_match(seed, cfg, match_001_schedule(cfg), "synthetic_001")
    else:
        sched = random_schedule(np.random.default_rng(seed + 10_000), cfg)
        m, _ = generate_match(seed, cfg, sched, f"synthetic_r{seed}")
    return MatchContext(parse_match_state(m), cfg)


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser(description="Gaffer agent: verify candidate shape changes")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--match", help="match_state JSON")
    src.add_argument("--synthetic-seed", type=int, help="generate a synthetic match (dev seeds)")
    ap.add_argument("--arm", choices=["llm", "rules"], default="llm")
    ap.add_argument("--view", default=None, help="camera view of a video match (top / side)")
    ap.add_argument("--candidates", default=None, help="comma-separated event ids")
    ap.add_argument("--max-candidates", type=int, default=None)
    ap.add_argument("--max-calls", type=int, default=None, help="run cap on LLM calls")
    ap.add_argument("--max-cost-usd", type=float, default=None, help="run cap on LLM cost")
    ap.add_argument("--alerts", default=None)
    ap.add_argument("--trace", default=None)
    args = ap.parse_args(argv)
    heldout = set(cfg["eval"]["synthetic"]["heldout_seeds_2"])
    if args.synthetic_seed in heldout:
        print("ERROR: seeds 110-119 are the final eval; use scripts/eval_agent.py --final",
              file=sys.stderr)
        return 2
    try:
        ctx = (_synthetic_context(args.synthetic_seed, cfg) if args.synthetic_seed is not None
               else MatchContext(load_match_state(args.match), cfg, view=args.view))
    except ContractError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    cands = ctx.candidates
    if args.candidates:
        want = set(args.candidates.split(","))
        cands = [c for c in cands if c.id in want]
    if args.max_candidates is not None:
        cands = cands[: args.max_candidates]
    llm = None
    if args.arm == "llm":
        from gaffer.llm.bedrock_client import BedrockClient
        try:
            llm = BedrockClient(cfg)
        except BedrockError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
    tb = Toolbox(ctx, AlertStore(args.alerts))
    runner = AgentRunner(ctx, tb, arm=args.arm, llm=llm,
                         budget=make_budget(cfg, args.max_calls, args.max_cost_usd),
                         trace=TraceWriter(args.trace or cfg["agent"]["outputs"]["trace"]))
    t0 = time.perf_counter()
    outcomes = runner.run(cands)
    for o in outcomes:
        print(f"{o.event_id} {o.decision:9s} by {o.decided_by:28s} llm {o.llm_calls} "
              f"blocks {o.guard_blocks}  {o.reason[:90]}")
    out = repo_path(f"outputs/{ctx.match.match_id}"
                    f"{cfg['agent']['outputs']['timeline_suffix']}")
    out.write_text(json.dumps(runner.verified_timeline(outcomes)), encoding="utf-8")
    b = runner.budget
    print(f"{len(outcomes)} candidates in {time.perf_counter() - t0:.0f} s | LLM calls "
          f"{b.calls}, tokens {dict(b.tokens)}, cost ${b.cost:.4f} | throttled "
          f"{runner.throttled} | -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
