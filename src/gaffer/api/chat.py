"""Chat with the analyst about ONE analysis (POST /api/chat; docs/API.md "Chat").

Read-only: the model can call the agent's five data tools (`get_match_overview`,
`get_formation_at`, `list_candidate_changes`, `get_metrics`, `compare_windows`, same code and
schemas as Phase 3) plus `get_decision` (the agent's verdict on one candidate) and
`get_timeline` (first-pass segments). No vision tool, no alert, nothing that writes.

Grounding (code, after the answer): every `[Rn]` cited must be a result of this question, every
`[evt_nnn]` a real candidate, an answer with numbers must cite something, and every number and
mm:ss clock in it must appear in this question's tool results (formation digits allowed). A
failed check gets one retry with the problems listed, then a safe "I can't answer that from this
analysis" reply. Caps (`api.chat`, `api.bedrock_daily`): tokens per question, questions per
visitor per day, Bedrock calls / cost per day for the whole API. Over a cap -> a polite refusal.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from gaffer.agent.tools import TOOLS, Toolbox, clock, tool_schema
from gaffer.llm.bedrock_client import BedrockError, tool_result_message, user_message

DATA_TOOLS = ("get_match_overview", "get_formation_at", "list_candidate_changes", "get_metrics",
              "compare_windows")

CHAT_SYSTEM = """You are Gaffer, a tactical analyst answering a football coach's questions about \
ONE analysed match. Use the tools to look things up; answer only from their results.

- Cite every fact with the ref of the tool result it came from, like [R2], or a candidate id \
like [evt_003]. Copy numbers and mm:ss times exactly as the results give them.
- Formations and segments are the tactics engine's first-pass reading; get_decision gives the \
agent's checked verdict on a candidate change (confirmed, rejected or uncertain) and its reason.
- The ball, possession and pressing are not measured on this camera: if asked, say so.
- If the data cannot answer the question, say that in one sentence and say what you can answer.
- At most 3 short sentences, plain words for a coach, no field names."""

SAFE_ANSWER = ("I can't answer that reliably from this analysis's data. I can tell you each "
               "team's shape at a given time, which shape changes Gaffer checked and why it "
               "confirmed or rejected them, and the defensive line, width and depth over a "
               "stretch of the match.")

REF_RE = re.compile(r"\[(R\d+)\]")
EVT_RE = re.compile(r"\[?(evt_\d{3})\]?")
FORMATION_RE = re.compile(r"\b\d(?:-\d){2,4}\b")
CLOCK_RE = re.compile(r"\b(\d{1,3}):([0-5]\d)\b")
NUM_RE = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")


class ChatRefused(Exception):
    """A cap or rule stops this question; `status_code` 429 (cap) / 503 (Bedrock) / 422."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class ChatSource:
    """One analysis the chat can read."""

    match_id: str  # the API id (demo id or analysis id)
    ctx: Any  # agent.context.MatchContext
    decisions: list[dict[str, Any]]
    alerts: list[dict[str, Any]] = field(default_factory=list)


def _extra_specs() -> list[dict[str, Any]]:
    return [
        {"toolSpec": {"name": "get_decision", "description":
                      "The agent's checked verdict on one candidate change: decision "
                      "(confirmed / rejected / uncertain / not checked), its reason, the "
                      "coach-facing explanation and the alert status.",
                      "inputSchema": {"json": {
                          "type": "object", "additionalProperties": False,
                          "required": ["event_id"],
                          "properties": {"event_id": {"type": "string",
                                                      "pattern": r"^evt_\d{3}$"}}}}}},
        {"toolSpec": {"name": "get_timeline", "description":
                      "First-pass formation segments of both teams (max 12) in a time span, "
                      "with defensive line, depth and width.",
                      "inputSchema": {"json": {
                          "type": "object", "additionalProperties": False,
                          "properties": {"from_s": {"type": "number", "minimum": 0},
                                         "to_s": {"type": "number", "minimum": 0}}}}}},
    ]


def chat_tool_specs() -> list[dict[str, Any]]:
    specs = [{"toolSpec": {"name": n, "description": TOOLS[n][1],
                           "inputSchema": {"json": tool_schema(n)}}} for n in DATA_TOOLS]
    return specs + _extra_specs()


class ChatTools:
    """Executes the read-only tools for one source; results stay small (<= ~1 KB)."""

    def __init__(self, src: ChatSource) -> None:
        self.src = src
        self.tb = Toolbox(src.ctx)  # read-only use: no store writes, no video
        self.decided = {d["event_id"]: d for d in src.decisions}
        for eid, d in self.decided.items():
            if eid in self.tb.statuses:
                self.tb.statuses[eid] = d["decision"]
        self.alerts = {a["event_id"]: a for a in src.alerts}

    def run(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        from pydantic import ValidationError

        from gaffer.agent.tools import _ToolFailure

        try:
            if name in DATA_TOOLS:
                parsed = TOOLS[name][0].model_validate(args or {})
                if name == "compare_windows":
                    return self._compare(parsed)
                result, _ = getattr(self.tb, f"_t_{name}")(None, parsed)
                return result
            if name == "get_decision":
                return self._decision(str((args or {}).get("event_id", "")))
            if name == "get_timeline":
                return self._timeline(args or {})
        except ValidationError as exc:
            return {"error": "invalid_args", "message": "; ".join(
                f"{'.'.join(map(str, e['loc'])) or 'args'}: {e['msg']}"
                for e in exc.errors()[:3])}
        except _ToolFailure as exc:
            return {"error": exc.code, "message": str(exc)[:200]}
        return {"error": "unknown_tool", "message": f"no tool {name!r}"}

    def _compare(self, a: Any) -> dict[str, Any]:
        a0, a1 = self.tb._window(a.a_start, a.a_end)
        b0, b1 = self.tb._window(a.b_start, a.b_end)
        wa, wb = self.tb._shares(a.team, a0, a1), self.tb._shares(a.team, b0, b1)
        delta = {k: round(wb[k] - wa[k], 1) for k in ("line_m", "width_m")
                 if wa[k] is not None and wb[k] is not None}
        return {"team": a.team, "a": wa, "b": wb, "delta": delta}

    def _decision(self, eid: str) -> dict[str, Any]:
        try:
            c = self.src.ctx.candidate(eid)
        except (KeyError, StopIteration, ValueError):
            return {"error": "unknown_event", "message": f"no candidate {eid!r}"}
        out: dict[str, Any] = {"event_id": c.id, "team": self.tb.team_name(c.team),
                               "change": f"{c.from_} -> {c.to}", "t": round(c.t, 1),
                               "clock": clock(c.t)}
        d = self.decided.get(c.id)
        if d is None:
            out["decision"] = "not checked by the agent"
        else:
            out.update(decision=d["decision"], reason=d.get("reason"),
                       explanation=(d.get("explanation") or "")[:300] or None)
        a = self.alerts.get(c.id)
        if a is not None:
            out["alert"] = {"status": a.get("status"), "title": a.get("title")}
        return out

    def _timeline(self, args: dict[str, Any]) -> dict[str, Any]:
        lo, hi = self.src.ctx.footage
        a = float(args.get("from_s", lo) or lo)
        b = float(args.get("to_s", hi) or hi)
        segs = [s for s in self.src.ctx.result.timeline.segments if s.end_s > a and s.start_s < b]
        items = []
        for s in segs[:12]:
            item: dict[str, Any] = {"span": f"{clock(s.start_s)}-{clock(s.end_s)}"}
            for side in ("home", "away"):
                t = getattr(s, side)
                item[self.tb.team_name(side)] = {
                    "formation": t.formation,
                    "line_m": None if t.defensive_line_m is None else round(t.defensive_line_m, 1),
                    "depth_m": None if t.compactness_m is None else round(t.compactness_m, 1),
                    "width_m": None if t.width_m is None else round(t.width_m, 1)}
            items.append(item)
        return {"total": len(segs), "returned": len(items), "segments": items}


# --------------------------------------------------------------------------- grounding


def _numbers(obj: Any, out: set[float], clocks: set[int], forms: set[int]) -> None:
    if isinstance(obj, dict):
        for v in obj.values():
            _numbers(v, out, clocks, forms)
    elif isinstance(obj, list | tuple):
        for v in obj:
            _numbers(v, out, clocks, forms)
    elif isinstance(obj, bool):
        return
    elif isinstance(obj, int | float):
        v = float(obj)
        out.add(round(v, 2))
        if 0 <= v <= 1:
            out.add(round(v * 100, 1))  # shares written as percentages
        if v >= 0:
            clocks.add(int(round(v)))  # match seconds written as mm:ss
    elif isinstance(obj, str):
        for m in CLOCK_RE.finditer(obj):
            clocks.add(int(m.group(1)) * 60 + int(m.group(2)))
        for f in FORMATION_RE.findall(obj):
            forms.update(int(x) for x in f.split("-"))
        for m in NUM_RE.finditer(FORMATION_RE.sub(" ", CLOCK_RE.sub(" ", obj))):
            out.add(round(float(m.group(0)), 2))


def check_answer(text: str, results: dict[str, dict[str, Any]], event_ids: set[str]
                 ) -> list[str]:
    """Problems with an answer (empty = grounded); see module docstring."""
    probs: list[str] = []
    if not text.strip():
        return ["empty answer"]
    refs = REF_RE.findall(text)
    evts = set(EVT_RE.findall(text))
    for r in refs:
        if r not in results:
            probs.append(f"[{r}] is not a result of this question")
    for e in evts - event_ids:
        probs.append(f"{e} is not a candidate of this match")
    allowed: set[float] = set()
    clocks: set[int] = set()
    forms: set[int] = set()
    _numbers(list(results.values()), allowed, clocks, forms)
    body = REF_RE.sub(" ", EVT_RE.sub(" ", text))
    for m in CLOCK_RE.finditer(body):
        s = int(m.group(1)) * 60 + int(m.group(2))
        if not any(abs(s - c) <= 5 for c in clocks):
            probs.append(f"time {m.group(0)} is not in the results")
    body = CLOCK_RE.sub(" ", body)
    body = FORMATION_RE.sub(" ", body)
    nums = [float(x) for x in NUM_RE.findall(body)]
    if nums and not refs and not evts:
        probs.append("an answer with numbers must cite the result it comes from, like [R1]")
    for x in nums:
        if x in forms and x == int(x):
            continue
        if not any(abs(x - v) <= max(0.051, 0.01 * abs(v)) for v in allowed):
            probs.append(f"number {x:g} is not in the results")
    return probs


# --------------------------------------------------------------------------- service


def _history(history: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    """Last `n` turns as Converse messages: roles alternate and the first one is the user."""
    msgs: list[dict[str, Any]] = []
    for h in history[-n:]:
        role = "assistant" if h.get("role") == "assistant" else "user"
        text = str(h.get("text", "")).strip()[:1000]
        if not text:
            continue
        if msgs and msgs[-1]["role"] == role:
            msgs[-1]["content"][0]["text"] += "\n" + text
        else:
            msgs.append({"role": role, "content": [{"text": text}]})
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    if msgs and msgs[-1]["role"] == "user":  # the new question must follow an answer
        msgs.append({"role": "assistant", "content": [{"text": "(no answer)"}]})
    return msgs


class ChatService:
    """Answers one question at a time over a `ChatSource` (LLM injected: tests mock it)."""

    def __init__(self, cfg: dict[str, Any], usage: Any, llm_factory: Any = None,
                 trace_path: Any = None) -> None:
        self.cfg, self.usage, self.llm_factory = cfg, usage, llm_factory
        self.c = cfg["api"]["chat"]
        self.model = cfg["bedrock"]["model_id"]
        self.prices = cfg["agent"]["llm"]["prices_per_1k"]
        self.trace_path = trace_path
        self._llm: Any = None

    def _price(self, model: str, tin: int, tout: int) -> float:
        pin, pout = self.prices.get(model, (0.0, 0.0))
        return tin / 1000 * float(pin) + tout / 1000 * float(pout)

    def llm(self) -> Any:
        if self._llm is None:
            if self.llm_factory is None:
                raise ChatRefused("The analyst chat needs Amazon Bedrock, which is not "
                                  "configured on this server. The analysis itself is all here.",
                                  503)
            try:
                self._llm = self.llm_factory()
            except BedrockError as exc:
                raise ChatRefused("The analyst (Amazon Bedrock) can't be reached right now: "
                                  f"{str(exc).splitlines()[0]}", 503) from exc
            if self._llm is None:
                raise ChatRefused("The analyst chat needs Amazon Bedrock, which is not "
                                  "configured on this server.", 503)
        return self._llm

    def ask(self, src: ChatSource, question: str, history: list[dict[str, Any]],
            visitor: str) -> dict[str, Any]:
        q = question.strip()
        if not q:
            raise ChatRefused("Please type a question.", 422)
        if len(q) > int(self.c["max_question_chars"]):
            raise ChatRefused(f"Please keep questions under {int(self.c['max_question_chars'])} "
                              "characters.", 422)
        calls_left, cost_left = self.usage.bedrock_left()
        if calls_left <= 0 or cost_left <= 0:
            raise ChatRefused("Gaffer's analyst has answered all the questions it can today "
                              "(daily limit for this demo). Please come back tomorrow; the "
                              "analysis, alerts and report stay available.", 429)
        llm = self.llm()
        left = self.usage.take_question(visitor)
        if left is None:
            raise ChatRefused("You've reached today's limit of "
                              f"{self.usage.max_questions} questions. Please come back "
                              "tomorrow.", 429)
        try:
            out = self._answer(llm, src, q, history)
        except BedrockError as exc:
            self.usage.refund_question(visitor)
            raise ChatRefused("The analyst (Amazon Bedrock) can't be reached right now: "
                              f"{str(exc).splitlines()[0]} Please try again in a minute.",
                              503) from exc
        except ChatRefused:
            self.usage.refund_question(visitor)
            raise
        out["questions_left_today"] = left
        return out

    def _answer(self, llm: Any, src: ChatSource, q: str, history: list[dict[str, Any]]
                ) -> dict[str, Any]:
        tools = ChatTools(src)
        specs = chat_tool_specs()
        msgs = _history(history, int(self.c["history_turns"])) + [user_message(q)]
        results: dict[str, dict[str, Any]] = {}
        sources: dict[str, dict[str, Any]] = {}
        used = {"in": 0, "out": 0, "calls": 0, "cost": 0.0}
        budget = int(self.c["max_tokens_per_request"])
        last_in = 1500
        trace_id = "chat_" + uuid.uuid4().hex[:10]
        rounds, retries, flags = 0, 0, []
        text = ""
        t0 = time.perf_counter()
        event_ids = {c.id for c in src.ctx.candidates}

        def call() -> Any:
            nonlocal last_in
            if used["in"] + used["out"] + last_in + int(self.c["max_answer_tokens"]) > budget:
                return None
            calls_left, cost_left = self.usage.bedrock_left()
            if calls_left <= 0 or cost_left <= self._price(self.model, last_in, 400):
                raise ChatRefused("Gaffer's analyst has reached its daily limit for this demo. "
                                  "Please come back tomorrow.", 429)
            r = llm.chat(msgs, system=CHAT_SYSTEM, tools=specs, model_id=self.model,
                         max_tokens=int(self.c["max_answer_tokens"]),
                         temperature=float(self.c["temperature"]), purpose="chat")
            tin, tout = int(r.usage.get("input_tokens", 0)), int(r.usage.get("output_tokens", 0))
            cost = self._price(r.model_id or self.model, tin, tout)
            used["in"] += tin
            used["out"] += tout
            used["calls"] += 1
            used["cost"] += cost
            last_in = max(tin, 1000)
            self.usage.add_bedrock(1, cost, tin, tout)
            return r

        max_rounds = int(self.c["max_tool_rounds"])
        grounded = False
        r = call()
        while r is not None:
            if r.tool_uses:
                if rounds >= max_rounds + 2:  # ignores "answer now": stop here
                    r = None
                    break
                pairs = []
                for u in r.tool_uses:
                    if rounds >= max_rounds:  # every toolUse needs a toolResult (Converse)
                        pairs.append((u.tool_use_id, {"error": "no_more_lookups", "message":
                                                      "Answer now from the results you have."}))
                        continue
                    ref = f"R{len(results) + 1}"
                    res = {"ref": ref, **tools.run(u.name, u.input)}
                    results[ref] = res
                    sources[ref] = {"tool": u.name, "args": u.input}
                    pairs.append((u.tool_use_id, res))
                rounds += 1
                msgs += [r.message, tool_result_message(pairs)]
                r = call()
                continue
            text = (r.text or "").strip()
            probs = check_answer(text, results, event_ids)
            if not probs:
                grounded = True
                break
            flags.append(probs)
            text = ""
            if retries >= int(self.c["retries"]):
                break
            retries += 1
            msgs += [{"role": "assistant", "content": [{"text": r.text or "(empty)"}]},
                     user_message("Your answer failed these checks:\n- " + "\n- ".join(
                         probs[:6]) + "\nAnswer again using only numbers and times from the "
                         "tool results, citing them like [R1].")]
            r = call()
        cites: list[str] = []
        if grounded:
            cites = list(dict.fromkeys(REF_RE.findall(text) + EVT_RE.findall(text)))
        elif r is None and not flags:
            text = ("That question needs more look-ups than one answer is allowed. Try a "
                    "narrower question, for example about one team or one stretch of the "
                    "match.")
        else:
            text = SAFE_ANSWER
        record = {"trace_id": trace_id, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  "match_id": src.match_id, "question": q[:500], "answer": text,
                  "citations": cites, "rounds": rounds, "retries": retries,
                  "flags": flags, "sources": sources, "llm": {
                      "calls": used["calls"], "in": used["in"], "out": used["out"],
                      "cost_usd": round(used["cost"], 6)},
                  "latency_ms": round((time.perf_counter() - t0) * 1000)}
        if self.trace_path is not None:
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            with self.trace_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
        return {"answer": text, "citations": cites, "trace_id": trace_id,
                "sources": {k: sources[k] for k in cites if k in sources},
                "grounded": grounded}
