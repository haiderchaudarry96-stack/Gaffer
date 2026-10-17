"""Agent tests (Phase 3, build steps 1-3). The LLM is always mocked: a scripted fake, or the real
`BedrockClient` on a botocore Stubber. No network (see the autouse guard in conftest)."""

from __future__ import annotations

import copy
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import boto3
import numpy as np
import pytest
from botocore.config import Config
from botocore.stub import ANY, Stubber

from gaffer.agent import explain
from gaffer.agent.alerts import AlertError, AlertStore, split_explanation, split_explanation_source
from gaffer.agent.context import MatchContext
from gaffer.agent.explain import Explainer
from gaffer.agent.loop import (
    AgentRunner,
    Budget,
    BudgetExceeded,
    RateLimiter,
    TraceWriter,
    make_budget,
)
from gaffer.agent.tools import TOOLS, Toolbox, clock, tool_schema, tool_specs
from gaffer.agent.verify import (
    Geometry,
    PassEvidence,
    VerifyConfig,
    allowed_decisions,
    decision_reason,
    evaluate,
    rules_decision,
)
from gaffer.config import load_config, repo_path
from gaffer.llm.bedrock_client import (
    BedrockCallError,
    BedrockClient,
    BedrockThrottlingError,
    ChatResult,
    ToolUse,
)
from gaffer.schema import parse_match_state
from gaffer.synthetic import Change, Schedule, generate_match

# --------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def agent_cfg() -> dict[str, Any]:
    c = copy.deepcopy(load_config())
    sc = c["synthetic"]
    sc["duration_s"], sc["half_time_s"] = 900.0, 450.0
    sc["noise_events"].update({"set_pieces": [0, 0], "counters": [0, 0], "flickers": [0, 0]})
    sc["camera"]["broadcast_fraction"] = 0.0
    return c


@pytest.fixture(scope="module")
def match(agent_cfg):
    sched = Schedule(start={"home": "4-4-2", "away": "5-3-2"},
                     changes=[Change("home", 300.0, "3-5-2")])
    m, _ = generate_match(7, agent_cfg, sched, "synthetic_test")
    return parse_match_state(m)


@pytest.fixture
def ctx(match, agent_cfg) -> MatchContext:
    c = MatchContext(match, agent_cfg)
    assert len(c.candidates) == 1, "fixture should give exactly one candidate"
    return c


@pytest.fixture
def toolbox(ctx, tmp_path) -> Toolbox:
    return Toolbox(ctx, AlertStore(tmp_path / "alerts.jsonl"), tmp_path / "evidence")


def ev(**kw: Any) -> PassEvidence:
    base = dict(source="first_pass", coverage_before=0.9, coverage_after=0.9, share_new=1.0,
                confident_after=12, windows_after=13, reverted_after_s=None, return_of=None,
                footage_frac=1.0)
    return PassEvidence(**{**base, **kw})


@pytest.fixture
def vcfg(agent_cfg) -> VerifyConfig:
    return VerifyConfig.from_config(agent_cfg)


# --------------------------------------------------------------------------- verify.py


def test_verdict_table(vcfg):
    def v(e, **kw):
        return evaluate(e, vcfg, **kw).verdict

    assert v(ev()) == "confirm"
    assert v(ev(reverted_after_s=35.0)) == "reject"
    assert v(ev(return_of="evt_001")) == "reject"
    assert v(ev(share_new=0.2)) == "reject"
    assert v(ev(share_new=0.5)) == "need_more"  # between persist_fail and persist_pass
    assert v(ev(confident_after=1)) == "need_more"
    assert v(ev(footage_frac=0.3)) == "uncertain"
    low = ev(coverage_before=0.2)
    r = evaluate(low, vcfg)
    assert r.verdict == "need_more" and "second_look" in r.missing and "coverage" in r.failed
    assert v(low, second_look=True) == "confirm"  # coverage asks for a look, never blocks
    assert v(ev(), view="side", backend="video", second_look=True,
             geometry=Geometry(1.0, 0, 0, False)) == "uncertain"


def test_return_leg_switch_is_off_and_only_spares_persisting_legs(vcfg):
    from dataclasses import replace
    leg = ev(return_of="evt_001")
    assert not vcfg.return_leg_needs_failed_persistence  # measured 17 Oct, OFF
    assert evaluate(leg, vcfg).verdict == "reject"
    on = replace(vcfg, return_leg_needs_failed_persistence=True)
    assert evaluate(leg, on).verdict == "confirm"
    assert evaluate(ev(return_of="evt_001", share_new=0.5), on).verdict == "reject"
    assert evaluate(ev(return_of="evt_001", reverted_after_s=30.0), on).verdict == "reject"


def test_video_needs_quality_and_second_look_even_for_a_reject(vcfg):
    r = evaluate(ev(reverted_after_s=20.0), vcfg, backend="video", view="top")
    assert r.verdict == "need_more" and set(r.missing) == {"quality_check", "second_look"}
    assert "suggests reject" in r.reason
    ok = Geometry(1.0, 1.0, 0.0, False)
    assert evaluate(ev(), vcfg, backend="video", view="top", geometry=ok,
                    second_look=True).verdict == "confirm"


def test_broken_camera_is_refused_before_anything_else(vcfg):
    pan = Geometry(0.2, 140.0, 0.2, False)
    assert evaluate(ev(), vcfg, backend="video", geometry=pan).verdict == "refuse"
    assert evaluate(None, vcfg, backend="video",
                    geometry=Geometry(1.0, 0.0, 0.0, True)).verdict == "refuse"


def test_allowed_decisions_never_less_cautious():
    assert allowed_decisions("confirm") == ("confirmed", "uncertain")
    assert allowed_decisions("reject") == ("rejected",)
    assert "confirmed" not in allowed_decisions("uncertain")
    assert allowed_decisions("need_more") == ()


def test_rules_decision_uses_reanalysis_only_when_needed(vcfg):
    dec, v, used = rules_decision(ev(), ev(share_new=0.1, source="reanalysis"), vcfg)
    assert (dec, used) == ("confirmed", False)
    dec, v, used = rules_decision(ev(coverage_after=0.3),
                                  ev(share_new=0.1, source="reanalysis"), vcfg)
    assert (dec, used) == ("rejected", True)
    dec, v, used = rules_decision(ev(share_new=0.5), ev(share_new=0.5), vcfg)
    assert dec == "uncertain"


# --------------------------------------------------------------------------- tools.py


def test_schemas_are_plain_and_strict():
    specs = tool_specs()
    assert len(specs) == 10
    text = json.dumps(specs)
    assert "$ref" not in text and "anyOf" not in text
    for name, (model, _) in TOOLS.items():
        s = tool_schema(name)
        assert s["type"] == "object" and s["additionalProperties"] is False
        assert set(s["properties"]) == set(model.model_fields)  # no field lost
        assert all("title" not in p for p in s["properties"].values())
    assert "title" in tool_schema("propose_alert")["required"]
    assert tool_schema("reanalyse_window")["properties"]["sample_fps"]["enum"] == [4, 6]


def test_every_tool_result_is_small(ctx, toolbox):
    c = ctx.candidates[0]
    st = toolbox.new_state(c)
    a, b = ctx.required_span(c)
    calls = [("get_match_overview", {}), ("get_formation_at", {"team": "home", "t": b}),
             ("list_candidate_changes", {}),
             ("get_metrics", {"team": "home", "start_s": a, "end_s": b}),
             ("compare_windows", {"team": "home", "a_start": a, "a_end": c.t,
                                  "b_start": c.detected_at_s, "b_end": b}),
             ("check_frame_quality", {"start_s": a, "end_s": b, "why": "t"}),
             ("reanalyse_window", {"start_s": a, "end_s": b, "sample_fps": 4,
                                   "event_id": c.id, "why": "t"})]
    for name, args in calls:
        res = toolbox.run(st, name, args)
        assert "error" not in res, (name, res)
        assert len(json.dumps(res)) <= 1024, (name, len(json.dumps(res)))
    assert [r for r in st.refs] == [f"R{i}" for i in range(len(calls) + 1)]


def test_protocol_guards(ctx, toolbox):
    c = ctx.candidates[0]
    st = toolbox.new_state(c)
    a, b = ctx.required_span(c)

    def run(name, **args):
        return toolbox.run(st, name, args)

    assert run("render_evidence", event_id=c.id, why="x")["error"] == "not_allowed"
    assert run("propose_alert", event_id=c.id, title="t", explanation="e [R0]",
               suggestion="s")["error"] == "not_allowed"
    # a confirmation needs a vision check even when the data already say "confirm"
    r = run("record_decision", event_id=c.id, decision="confirmed", reason="held",
            citations=[{"ref": "R0"}])
    assert r["error"] == "not_allowed" and "vision check" in r["message"]
    assert run("get_metrics", team="x")["error"] == "invalid_args"
    assert run("nope")["error"] == "unknown_tool"
    q = run("check_frame_quality", start_s=a, end_s=b, why="x")
    assert "error" not in q
    assert run("record_decision", event_id=c.id, decision="confirmed", reason="held",
               citations=[{"ref": "R99"}])["error"] == "not_allowed"
    r = run("record_decision", event_id=c.id, decision="confirmed",
            reason="held since 99:00", citations=[{"ref": q["ref"]}])
    assert r["error"] == "not_allowed" and "99:00" in r["message"]
    assert run("record_decision", event_id="evt_999", decision="rejected", reason="x",
               citations=[{"ref": q["ref"]}])["error"] == "not_allowed"


def test_full_confirm_path_creates_pending_alert_and_png(ctx, toolbox, tmp_path):
    c = ctx.candidates[0]
    st = toolbox.new_state(c)
    a, b = ctx.required_span(c)
    q = toolbox.run(st, "check_frame_quality", {"start_s": a, "end_s": b, "why": "x"})
    assert q["rules"]["verdict"] == "confirm", q
    assert toolbox.run(st, "record_decision", {"event_id": c.id, "decision": "confirmed",
                                               "reason": "held", "citations": [
                                                   {"ref": q["ref"]}]})["ok"]
    img = toolbox.run(st, "render_evidence", {"event_id": c.id, "why": "x"})
    assert Path(repo_path(img["image"])).exists() and img["bytes"] > 1000
    r = toolbox.run(st, "propose_alert", {"event_id": c.id, "title": "Blue to a back three",
                                          "explanation": f"held [{q['ref']}]",
                                          "suggestion": "watch the wings"})
    assert r["status"] == "pending" and st.done
    assert AlertStore(tmp_path / "alerts.jsonl").get(r["alert_id"]).status == "pending"


# --------------------------------------------------------------------------- alerts.py


def test_alert_store_append_only_last_line_wins(tmp_path):
    s = AlertStore(tmp_path / "a.jsonl")
    a = s.create("m1", "evt_001", 300.0, "t", "e [R1]", "s", None)
    assert a.alert_id == "alr_m1_evt_001" and a.status == "pending"
    with pytest.raises(AlertError):
        s.create("m1", "evt_001", 300.0, "t", "e", "s", None)
    s.decide(a.alert_id, approve=True, note="ok")
    assert s.get(a.alert_id).status == "approved"
    assert len((tmp_path / "a.jsonl").read_text().splitlines()) == 2
    with pytest.raises(AlertError):
        s.decide(a.alert_id, approve=False)
    with pytest.raises(AlertError):
        s.decide("alr_nope", approve=True)


# --------------------------------------------------------------------------- loop.py


class FakeLLM:
    """Scripted LLM: each item is a list of (tool, args) calls, a str (text reply) or an
    exception; a callable item gets the messages and returns one of those."""

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages, system=None, tools=None, tool_choice=None, model_id=None,
             max_tokens=None, temperature=None, purpose=""):
        self.calls.append({"messages": copy.deepcopy(messages), "tool_choice": tool_choice,
                           "model_id": model_id})
        if not self.script:
            raise AssertionError("FakeLLM script exhausted")
        item = self.script.pop(0)
        if callable(item) and not isinstance(item, type):
            item = item(messages)
        if isinstance(item, Exception):
            raise item
        usage = {"input_tokens": 2000, "output_tokens": 50, "total_tokens": 2050}
        if isinstance(item, str):
            msg = {"role": "assistant", "content": [{"text": item}]}
            return ChatResult(item, [], "end_turn", msg, model_id, 1.0, 1, usage)
        uses = [ToolUse(f"tu{len(self.calls)}_{i}", n, a) for i, (n, a) in enumerate(item)]
        msg = {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": u.tool_use_id, "name": u.name, "input": u.input}}
            for u in uses]}
        return ChatResult("", uses, "tool_use", msg, model_id, 1.0, 1, usage)


def _runner(ctx, toolbox, llm, tmp_path, **kw) -> AgentRunner:
    # the orchestration scripts here have no explanation turns: template explanations unless a
    # test passes its own explainer (the explanation step is its own conversation)
    return AgentRunner(ctx, toolbox, arm=kw.pop("arm", "llm"), llm=llm,
                       budget=kw.pop("budget", make_budget(ctx.cfg)),
                       limiter=RateLimiter(1000, sleep=lambda s: None),
                       trace=TraceWriter(tmp_path / "trace.jsonl"), run_id="test",
                       explainer=kw.pop("explainer", Explainer(ctx.cfg)), **kw)


def _trace(tmp_path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in (tmp_path / "trace.jsonl").read_text().splitlines()]


def _patch_evidence(ctx, first: PassEvidence, re: PassEvidence) -> None:
    ctx.evidence = lambda cand, data=None: first if data is None else re  # type: ignore


def _span(ctx):
    c = ctx.candidates[0]
    a, b = ctx.required_span(c)
    return c, a, b


def test_situation_b_low_coverage_second_look_confirms_then_alert(ctx, toolbox, tmp_path):
    _patch_evidence(ctx, ev(coverage_after=0.4), ev(source="reanalysis"))
    c, a, b = _span(ctx)
    llm = FakeLLM([
        [("check_frame_quality", {"start_s": a, "end_s": b, "why": "quality first"})],
        [("reanalyse_window", {"start_s": a, "end_s": b, "sample_fps": 6, "event_id": c.id,
                               "why": "coverage 0.4: second look"})],
        [("record_decision", {"event_id": c.id, "decision": "confirmed",
                              "reason": "held in 100% of windows", "citations": [{"ref": "R2"}]})],
        [("render_evidence", {"event_id": c.id, "why": "proof"})],
        [("propose_alert", {"event_id": c.id, "title": "Blue switched to 3-5-2",
                            "explanation": "The back three held for a minute [R2].",
                            "suggestion": "Attack the space behind the wing-backs."})],
    ])
    out = _runner(ctx, toolbox, llm, tmp_path).run()[0]
    assert (out.decision, out.decided_by, out.llm_calls) == ("confirmed", "agent", 5)
    assert out.alert_id and out.guard_blocks == 0
    tr = _trace(tmp_path)
    calls = [r for r in tr if r["kind"] == "tool_call"]
    assert [r["tool"] for r in calls] == ["check_frame_quality", "reanalyse_window",
                                          "record_decision", "render_evidence", "propose_alert"]
    # the vision result is what the next call reacted to
    assert calls[0]["result_summary"]["rules"]["verdict"] == "need_more"
    assert calls[1]["prev_ref"] == "R1" and calls[1]["result_summary"]["rules"]["verdict"] \
        == "confirm"
    assert tr[-2]["kind"] == "decision" and tr[-2]["decision"] == "confirmed"
    assert tr[-1]["kind"] == "match_summary" and tr[-1]["llm_calls"] == 5
    assert llm.calls[0]["tool_choice"] == "any"


def test_alert_never_shows_a_reason_that_contradicts_the_rules_verdict(ctx, toolbox, tmp_path):
    """Problem 1 (spike 15 Oct): the model's text can contradict its own cited results. The
    alert title, the alert's primary reason and the verified timeline are written by code from
    the verdict; since step 7 the model's orchestration text (record_decision / propose_alert)
    stays in the trace only, and the alert's explanation comes from agent/explain.py."""
    _patch_evidence(ctx, ev(coverage_after=0.4), ev(source="reanalysis"))
    c, a, b = _span(ctx)
    lie = "Re-analysis shows the shape reverted after 30 s"
    llm = FakeLLM([
        [("reanalyse_window", {"start_s": a, "end_s": b, "sample_fps": 4, "event_id": c.id,
                               "why": "second look"})],
        [("record_decision", {"event_id": c.id, "decision": "confirmed", "reason": lie,
                              "citations": [{"ref": "R1"}]})],
        [("render_evidence", {"event_id": c.id, "why": "proof"})],
        [("propose_alert", {"event_id": c.id, "title": "Red moved to a 5-4-1",
                            "explanation": f"{lie} [R1].", "suggestion": "Press high."})],
    ])
    r = _runner(ctx, toolbox, llm, tmp_path)
    out = r.run()[0]
    verdict = evaluate(ev(source="reanalysis"), ctx.vcfg, second_look=True)
    assert verdict.verdict == "confirm" and out.decision == "confirmed"
    assert out.reason == verdict.reason
    assert out.explanation_source == "template" and lie not in out.explanation
    alert = AlertStore(tmp_path / "alerts.jsonl").get(out.alert_id)
    rules, text, source = split_explanation_source(alert.explanation)
    assert rules == f"{verdict.reason} [R1]" and "reverted" not in rules
    assert source == "template" and text == out.explanation and lie not in alert.explanation
    assert split_explanation(alert.explanation) == (rules, text)
    assert alert.title == f"{toolbox.team_name(c.team)}: {c.from_} -> {c.to} ({clock(c.t)})"
    ver = r.verified_timeline([out])["events"][0]["verification"]
    assert ver["reason"] == verdict.reason
    dec = [x for x in _trace(tmp_path) if x["kind"] == "decision"][0]
    assert (dec["reason"], dec["decision_text"]) == (verdict.reason, lie)
    assert dec["explanation"] == out.explanation


def test_decision_reason_restates_the_verdict_and_marks_caution(vcfg):
    conf = evaluate(ev(), vcfg)
    assert decision_reason(conf, "confirmed") == conf.reason
    cautious = decision_reason(conf, "uncertain")
    assert cautious.startswith("rules: confirm") and "more cautious" in cautious
    rej = evaluate(ev(reverted_after_s=30.0), vcfg)
    assert decision_reason(rej, "rejected") == rej.reason
    nm = evaluate(ev(share_new=0.5), vcfg)
    assert decision_reason(nm, "uncertain").startswith("no verdict")


# --------------------------------------------------------------------------- explain.py


def _decided(ctx, toolbox, first: PassEvidence, second: PassEvidence, decision: str):
    """A candidate decided through the toolbox on patched evidence (quality check, second look,
    record_decision), as the loop leaves it before the explanation step."""
    _patch_evidence(ctx, first, second)
    c, a, b = _span(ctx)
    st = toolbox.new_state(c)
    toolbox.run(st, "check_frame_quality", {"start_s": a, "end_s": b, "why": "q"})
    toolbox.run(st, "reanalyse_window", {"start_s": a, "end_s": b, "sample_fps": 4,
                                         "event_id": c.id, "why": "second look"})
    r = toolbox.run(st, "record_decision", {"event_id": c.id, "decision": decision,
                                             "reason": "x", "citations": [{"ref": "R2"}]})
    assert r.get("ok"), r
    return st


EXPLAIN_CASES = {  # cause -> first pass, second look, decision
    "held": (ev(coverage_after=0.4), ev(source="reanalysis", share_new=0.91, confident_after=11),
             "confirmed"),
    "revert": (ev(coverage_after=0.4),
               ev(source="reanalysis", share_new=0.17, reverted_after_s=55.0), "rejected"),
    "return_leg": (ev(return_of="evt_000"),
                   ev(source="reanalysis", share_new=0.75, return_of="evt_000"), "rejected"),
    "persistence": (ev(coverage_after=0.4),
                    ev(source="reanalysis", share_new=0.27, confident_after=11), "rejected"),
    "footage": (ev(footage_frac=0.5), ev(source="reanalysis", footage_frac=0.5), "uncertain"),
    "inconclusive": (ev(coverage_after=0.4),
                     ev(source="reanalysis", share_new=0.57, confident_after=7), "uncertain"),
}


@pytest.mark.parametrize("cause", sorted(EXPLAIN_CASES))
def test_template_names_the_code_cause_and_passes_its_own_check(ctx, toolbox, cause):
    first, second, decision = EXPLAIN_CASES[cause]
    st = _decided(ctx, toolbox, first, second, decision)
    f = explain.facts(toolbox, st)
    assert f["cause"] == cause and f["code_reason"] == st.reason
    assert "held 20s" not in explain.prompt(f) and "engine evidence" not in explain.prompt(f)
    text = explain.template(f)
    assert explain.check(text, f, ctx.cfg) == [], text
    assert re.search(r"\[R\d\]", text)


def test_check_flags_the_17_oct_failure_texts(ctx, toolbox):
    """The wrong real-footage explanations of 17 Oct (FAILURE_LOG) are all caught."""
    def flags(cause, text):
        first, second, decision = EXPLAIN_CASES[cause]
        st = _decided(ctx, toolbox, first, second, decision)
        return explain.check(text, explain.facts(toolbox, st), ctx.cfg)

    # a return leg that held 75 %: "no transition occurred" (eval2 evt_003)
    f1 = flags("return_leg", "Re-analysis shows formation held as 4-4-2 throughout window; "
                             "no transition to 3-4-3 occurred [R2]")
    assert any("did not hold" in x for x in f1) and any("cause" in x for x in f1)
    # footage-limited explained as engine confidence (eval2 evt_005)
    f2 = flags("footage", "Vision quality sufficient but engine confidence alone insufficient "
                          "for confirmation [R0][R1]")
    assert any("confidence" in x for x in f2) and any("cause (footage)" in x for x in f2)
    # the false flag of the 17 Oct real run ("... is recorded") names the cause since then
    assert flags("footage", "We can't say for sure: not all of the next minute is recorded "
                            "[R0].") == []
    # the engine's persistence rule copied into a confirmed alert (31 of 41 synthetic alerts)
    f3 = flags("held", "Home changed shape, held for over 20 seconds with good visibility [R2].")
    assert any("20 s" in x for x in f3)
    # numbers must be copied as written; unavailable data is never mentioned
    assert any("0.91" in x for x in flags("held", "The shape held in 0.91 of readings [R2]."))
    assert any("unavailable" in x for x in flags("held", "It held in 91% of readings and the "
                                                         "pressing improved [R2]."))
    assert any("do not exist" in x for x in flags("held", "It held in 91% of readings [R9]."))
    assert flags("held", "Blue kept the 3-5-2: it showed in 91% of 11 clear readings over the "
                         "next 60 s [R2].") == []
    assert flags("persistence", "The 3-5-2 did not last: it showed in only 27% of 11 clear "
                                "readings [R2].") == []


def test_flagged_model_explanation_is_replaced_and_decisions_do_not_move(ctx, toolbox,
                                                                         tmp_path):
    _patch_evidence(ctx, ev(coverage_after=0.4),
                    ev(source="reanalysis", share_new=0.91, confident_after=11))
    c, a, b = _span(ctx)

    def orchestration():
        return FakeLLM([
            [("reanalyse_window", {"start_s": a, "end_s": b, "sample_fps": 4, "event_id": c.id,
                                   "why": "second look"})],
            [("record_decision", {"event_id": c.id, "decision": "confirmed", "reason": "held",
                                  "citations": [{"ref": "R1"}]})],
            [("render_evidence", {"event_id": c.id, "why": "proof"})],
            [("propose_alert", {"event_id": c.id, "title": "t", "explanation": "held [R1]",
                                "suggestion": "s"})]])

    bad = FakeLLM(["The new shape held for 20 seconds [R1]."])
    out = _runner(ctx, toolbox, orchestration(), tmp_path,
                  explainer=Explainer(ctx.cfg, llm=bad)).run()[0]
    assert out.decision == "confirmed" and out.explanation_source == "template"
    assert any("20 s" in x for x in out.explanation_flags) and out.explain_calls == 1
    assert len(bad.calls) == 1 and bad.calls[0]["tool_choice"] is None  # its own conversation
    ex = [x for x in _trace(tmp_path) if x["kind"] == "explanation"][-1]
    assert ex["replaced_text"].startswith("The new shape held for 20 seconds")
    alert = AlertStore(tmp_path / "alerts.jsonl").get(out.alert_id)
    assert split_explanation_source(alert.explanation)[1:] == (out.explanation, "template")

    good_text = (f"{toolbox.team_name(c.team)} kept the {c.to} after {clock(c.t)}: it showed in "
                 "91% of 11 clear readings over the next 60 s [R1].")
    good = FakeLLM([good_text])
    tb2 = Toolbox(ctx, AlertStore(tmp_path / "alerts2.jsonl"), tmp_path / "evidence2")
    out2 = _runner(ctx, tb2, orchestration(), tmp_path,
                   explainer=Explainer(ctx.cfg, llm=good)).run()[0]
    assert (out2.explanation_source, out2.explanation) == ("agent", good_text)
    assert (out2.decision, out2.reason, out2.tool_calls) == (out.decision, out.reason,
                                                             out.tool_calls)


def test_explainer_budget_and_errors_fall_back_without_raising(ctx, toolbox):
    first, second, decision = EXPLAIN_CASES["revert"]
    f = explain.facts(toolbox, _decided(ctx, toolbox, first, second, decision))
    idle = FakeLLM([])
    e = Explainer(ctx.cfg, llm=idle, max_cost_usd=0.0).explain(f)
    assert e.source == "template" and "budget" in e.flags[0] and idle.calls == []
    broken = FakeLLM([BedrockCallError("ValidationException: boom")])
    e = Explainer(ctx.cfg, llm=broken).explain(f)
    assert e.source == "template" and e.flags[0].startswith("llm error")
    assert Explainer(ctx.cfg, llm=FakeLLM(["x"])).explain(f, use_llm=False).source == "template"


def test_before_panel_skips_windows_with_the_team_packed_in_its_own_box(ctx, toolbox,
                                                                        monkeypatch):
    """Step 7: the 16:30 demo alert's "before" panel showed a set piece (team in its own box).
    The panel takes the most confident window that is not packed; if all are, it says so."""
    c = ctx.candidates[0]
    lo = c.t - float(ctx.cfg["presentation"]["evidence"]["before_search_s"])
    ws = toolbox.family_windows(ctx.first, c.team, c.from_, lo, c.t)
    assert len(ws) >= 2
    best = max(ws, key=lambda w: (w.confidence, w.t))
    span = f"{clock(best.t - best.window_s)}-{clock(best.t)}"
    monkeypatch.setattr(toolbox, "own_box_share", lambda d, team, w: 0.6 if w is best else 0.1)
    before = toolbox.shape_panels(c, ctx.first)[0]
    assert before["typical"] and before["note"].startswith("usual shape")
    assert span not in before["caption"] and before["own_box_share"] == 0.1
    monkeypatch.setattr(toolbox, "own_box_share", lambda d, team, w: 0.6)
    before = toolbox.shape_panels(c, ctx.first)[0]
    assert not before["typical"] and before["note"].startswith("ATYPICAL")
    assert span in before["caption"]


def test_own_box_share_counts_positions_inside_the_own_penalty_area(ctx, toolbox):
    from types import SimpleNamespace

    from gaffer.agent.context import PassData
    from gaffer.tactics.common import TeamFrame

    pts = np.array([[10.0, 34.0]] * 8 + [[40.0, 34.0]] * 2)  # 8 in the box, 2 at 40 m
    frames = [TeamFrame(t=float(t), outfield=pts, n_visible=11, ball=None, possession=None)
              for t in range(31)]
    data = PassData({"home": [], "away": []}, [], {"home": frames, "away": []}, (0.0, 30.0), 1.0)
    w = SimpleNamespace(t=30.0, window_s=30.0)
    assert toolbox.own_box_share(data, "home", w) == pytest.approx(0.8)
    wide = pts.copy()
    wide[:, 1] = 5.0  # same depth, outside the box width (34 +- 20.16 m)
    data.frames["home"] = [TeamFrame(t=float(t), outfield=wide, n_visible=11, ball=None,
                                     possession=None) for t in range(31)]
    assert toolbox.own_box_share(data, "home", w) == 0.0


def test_side_reason_leads_with_the_experimental_camera(match, agent_cfg, tmp_path):
    """Step 7: the side eval2 candidate's recorded reason said "no verdict after the evidence
    budget" although the camera alone keeps it below an alert. Presentation only: the verdict
    and the decision are unchanged."""
    side = MatchContext(match, agent_cfg, view="side")
    tb = Toolbox(side, AlertStore(tmp_path / "a.jsonl"), tmp_path / "ev")
    _patch_evidence(side, ev(share_new=0.57, confident_after=7), ev(share_new=0.57))
    c = side.candidates[0]
    st = tb.new_state(c)
    assert st.verdict.verdict == "need_more"
    tb._err(st, st.next_ref(), "reanalyse_window", None, "over_budget",
            "estimated 1568 s of OpenCV > 360 s for 140 s at 4 fps")
    st.exhausted = True
    r = tb.run(st, "record_decision", {"event_id": c.id, "decision": "uncertain",
                                        "reason": "x", "citations": [{"ref": "R0"}]})
    assert r["ok"] and st.decision == "uncertain" and st.verdict.verdict == "need_more"
    assert st.reason.startswith("uncertain: experimental camera (side view, never alerted)")
    assert st.reason.index("over budget (estimated 1568 s") < st.reason.index(
        "first pass: new shape held in 57% of windows (inconclusive)")
    assert r["recorded_reason"] == st.reason
    f = explain.facts(tb, st)
    assert f["cause"] == "experimental_camera"
    assert explain.check(explain.template(f), f, agent_cfg) == []
    # held but capped by the view: the camera first, the share as detail
    _patch_evidence(side, ev(), ev())
    held = tb.new_state(c)
    tb.run(held, "check_frame_quality", {"start_s": c.t - 45, "end_s": c.detected_at_s + 60,
                                         "why": "q"})
    assert held.verdict.verdict == "uncertain" and held.verdict.failed == ["view"]
    tb.run(held, "record_decision", {"event_id": c.id, "decision": "uncertain", "reason": "x",
                                     "citations": [{"ref": "R1"}]})
    assert held.reason == ("uncertain: experimental camera (side view, never alerted); "
                           "detail: new shape held in 100% of 12 confident windows")
    # a top-view uncertain decision keeps the plain reason
    assert not decision_reason(evaluate(ev(share_new=0.57), side.vcfg), "uncertain").startswith(
        "uncertain: experimental")


# --------------------------------------------------------------------------- report.py


def _report_inputs(ctx):
    from gaffer.agent import report

    c = ctx.candidates[0]
    decided = [{"event_id": c.id, "decision": "confirmed",
                "reason": "new shape held in 100% of 12 confident windows over 60 s, no revert",
                "explanation": "Blue kept the 3-5-2 [R1].", "new_shape_pct": 100}]
    return report.build_inputs(ctx, decided, note="Synthetic test match.")


def test_template_report_is_grounded_and_passes_its_own_check(ctx):
    from gaffer.agent import report

    inp = _report_inputs(ctx)
    assert [e["id"] for e in inp["events"]] == [ctx.candidates[0].id]
    assert inp["events"][0]["before"]["window"] and inp["events"][0]["after"]["width_m"]
    rep = report.template_report(inp)
    assert report.check_report(rep, inp, ctx.cfg) == []
    assert len(rep["recommendations"]) == 3 and rep["changes"][0]["event"] == "evt_001"
    md = report.render_markdown(rep, inp, "code template")
    assert "## Three recommendations" in md and "Synthetic test match." in md


def test_report_check_catches_uncited_and_invented_claims(ctx):
    from gaffer.agent import report

    inp = _report_inputs(ctx)
    good = report.template_report(inp)

    def probs(**change):
        rep = copy.deepcopy(good)
        for k, v in change.items():
            rep[k] = v
        return report.check_report(rep, inp, ctx.cfg)

    seg = inp["segments"][0]["seg"]
    assert any("no citation" in p for p in probs(formation_story=[
        f"Blue lined up in a 4-4-2 until {seg.split('-')[1]}."]))
    assert any("not in the cited items" in p for p in probs(formation_story=[
        f"Blue's line sat 99.9 m from goal [seg {seg}]."]))
    assert any("not a source" in p for p in probs(limits=["Demo window [match.note]."]))
    assert any("not 3" in p for p in probs(recommendations=good["recommendations"][:2]))
    assert any("unavailable" in p for p in probs(limits=["We could not see the ball."]))
    assert any("not a decided event" in p for p in probs(not_alerted=["Gone at 1:00 [evt_099]."]))
    assert any("no cited number" in p for p in probs(recommendations=[
        "Work harder.", *good["recommendations"][1:]]))
    assert any("says nothing about" in p for p in probs(formation_story=["Fine [seg " + seg
                                                                         + "]."]))


def test_reporter_retries_once_then_uses_the_template(ctx):
    from gaffer.agent import report

    inp = _report_inputs(ctx)
    bad = FakeLLM(["not json", '{"formation_story": "one string"}'])
    res = report.Reporter(ctx.cfg, bad).generate(inp)
    assert res["source"] == "code template" and len(bad.calls) == 2
    assert res["template_problems"] == [] and len(res["attempts"]) == 2
    good = FakeLLM(["```json\n" + json.dumps(report.template_report(inp)) + "\n```"])
    res = report.Reporter(ctx.cfg, good).generate(inp)
    assert res["source"] == "Nova 2 Lite (checked)" and len(good.calls) == 1


def test_rules_block_names_the_next_step(ctx, toolbox):
    """Problem 2: record_decision comes before render_evidence."""
    c, a, b = _span(ctx)
    st = toolbox.new_state(c)
    assert f"next step: {toolbox.next_step(st)}" in toolbox.card(st)
    # first-pass "confirm" still needs a vision check before any confirmation (guard)
    assert st.verdict.verdict == "confirm"
    assert toolbox.next_step(st).startswith("check_frame_quality")
    q = toolbox.run(st, "check_frame_quality", {"start_s": a, "end_s": b, "why": "q"})
    assert q["rules"]["verdict"] == "confirm"
    assert q["rules"]["next_step"].startswith("record_decision(confirmed or uncertain)")
    d = toolbox.run(st, "record_decision", {"event_id": c.id, "decision": "confirmed",
                                            "reason": "held", "citations": [{"ref": q["ref"]}]})
    assert d["next"] == "render_evidence" and d["recorded_reason"] == st.verdict.reason


def test_situation_c_second_look_disagrees_and_confirm_is_blocked(ctx, toolbox, tmp_path):
    _patch_evidence(ctx, ev(coverage_after=0.4),
                    ev(source="reanalysis", share_new=0.33, reverted_after_s=45.0))
    c, a, b = _span(ctx)
    llm = FakeLLM([
        [("reanalyse_window", {"start_s": a, "end_s": b, "sample_fps": 4, "event_id": c.id,
                               "why": "second look"})],
        [("record_decision", {"event_id": c.id, "decision": "confirmed", "reason": "x",
                              "citations": [{"ref": "R1"}]})],
        [("record_decision", {"event_id": c.id, "decision": "rejected",
                              "reason": "reverted after 45 s", "citations": [{"ref": "R1"}]})],
    ])
    out = _runner(ctx, toolbox, llm, tmp_path).run()[0]
    assert (out.decision, out.decided_by, out.guard_blocks) == ("rejected", "agent", 1)
    assert out.alert_id is None


def test_situation_d_inconclusive_is_uncertain_not_alerted(ctx, toolbox, tmp_path):
    _patch_evidence(ctx, ev(coverage_after=0.4), ev(source="reanalysis", share_new=0.5))
    c, a, b = _span(ctx)
    llm = FakeLLM([
        [("record_decision", {"event_id": c.id, "decision": "uncertain", "reason": "x",
                              "citations": [{"ref": "R0"}]})],  # need_more: not allowed yet
        [("reanalyse_window", {"start_s": a, "end_s": b, "sample_fps": 4, "event_id": c.id,
                               "why": "second look"})],
        [("record_decision", {"event_id": c.id, "decision": "uncertain",
                              "reason": "held in only half the windows",
                              "citations": [{"ref": "R2"}]})],
    ])
    out = _runner(ctx, toolbox, llm, tmp_path).run()[0]
    assert (out.decision, out.decided_by, out.guard_blocks) == ("uncertain", "agent", 1)


def test_situation_e_return_leg_rejected_without_vision(ctx, toolbox, tmp_path):
    _patch_evidence(ctx, ev(return_of="evt_000"), ev(return_of="evt_000"))
    c, _, _ = _span(ctx)
    llm = FakeLLM([[("record_decision", {"event_id": c.id, "decision": "rejected",
                                         "reason": "returns to the earlier shape",
                                         "citations": [{"ref": "R0"}]})]])
    out = _runner(ctx, toolbox, llm, tmp_path).run()[0]
    assert (out.decision, out.llm_calls, out.tool_calls) == ("rejected", 1, ["record_decision"])


def test_text_replies_are_nudged_once_then_rules_finish(ctx, toolbox, tmp_path):
    llm = FakeLLM(["I think it is real.", "Still thinking."])
    out = _runner(ctx, toolbox, llm, tmp_path).run()[0]
    assert out.fallback == "guard: no tool call" and out.decided_by == "guard: no tool call"
    assert out.decision == "confirmed" and out.alert_id  # the rules policy finished the job
    assert "check_frame_quality" in out.tool_calls


def test_malformed_calls_twice_fall_back(ctx, toolbox, tmp_path):
    llm = FakeLLM([[("get_metrics", {"team": "x"})], [("made_up", {})]])
    out = _runner(ctx, toolbox, llm, tmp_path).run()[0]
    assert out.fallback == "guard: malformed calls" and out.invalid_calls == 2


def test_identical_call_cached_then_stopped(ctx, toolbox, tmp_path):
    call = [("get_match_overview", {})]
    llm = FakeLLM([call, call, call])
    out = _runner(ctx, toolbox, llm, tmp_path).run()[0]
    assert out.fallback == "guard: repeated call"
    tr = _trace(tmp_path)
    assert any(r.get("kind") == "guard_block" for r in tr)


def test_step_limit(ctx, toolbox, tmp_path):
    llm = FakeLLM([[("get_formation_at", {"team": "home", "t": 100.0 + i})] for i in range(8)])
    out = _runner(ctx, toolbox, llm, tmp_path).run()[0]
    assert out.llm_calls == 8 and out.fallback == "guard: step limit"
    assert out.decision in ("confirmed", "rejected", "uncertain")


def test_quota_exhausted_switches_the_rest_to_rules(ctx, toolbox, tmp_path):
    cand = ctx.candidates[0]
    llm = FakeLLM([BedrockThrottlingError("Too many tokens per day", quota_exhausted=True)])
    r = _runner(ctx, toolbox, llm, tmp_path)
    outs = r.run([cand, cand.__class__(**{**cand.__dict__, "id": "evt_002"})])
    assert r.llm_down == "quota exhausted" and r.throttled == 1
    assert outs[0].decided_by.startswith("rules (llm unavailable")
    assert outs[1].llm_calls == 0 and outs[1].fallback.startswith("rules (quota")
    assert len(llm.calls) == 1


def test_run_budget_caps_calls(ctx, toolbox, tmp_path):
    b = make_budget(ctx.cfg, max_calls_run=2)
    llm = FakeLLM([[("get_formation_at", {"team": "home", "t": 100.0 + i})] for i in range(5)])
    out = _runner(ctx, toolbox, llm, tmp_path, budget=b).run()[0]
    assert len(llm.calls) == 2 and out.fallback.startswith("rules (budget")


def test_cost_cap_is_checked_before_the_call():
    b = Budget(prices={"m": [0.001, 0.001]}, max_calls_match=100, max_tokens_match=10**9,
               max_cost_match=100.0, max_cost_run=0.004, max_tokens_out=400)
    # worst case for the next call: (3000 + 1000) in + 400 out tokens = 0.0044 USD > 0.004
    with pytest.raises(BudgetExceeded, match="run cost cap"):
        b.check_next("m")
    with pytest.raises(BudgetExceeded, match="no price"):
        b.check_next("unknown-model")


def test_tool_choice_any_falls_back_to_auto(ctx, toolbox, tmp_path):
    c, a, b = _span(ctx)
    llm = FakeLLM([BedrockCallError("ValidationException: toolChoice any not supported"),
                   [("check_frame_quality", {"start_s": a, "end_s": b, "why": "q"})],
                   [("record_decision", {"event_id": c.id, "decision": "uncertain",
                                         "reason": "x", "citations": [{"ref": "R1"}]})]])
    r = _runner(ctx, toolbox, llm, tmp_path)
    r.run()
    assert r.tool_choice == "auto" and r.tool_choice_any_ok is False
    assert llm.calls[1]["tool_choice"] == "auto"


def test_rate_limiter_waits_when_the_minute_is_full():
    now = [0.0]
    slept: list[float] = []
    lim = RateLimiter(3, clock_fn=lambda: now[0], sleep=lambda s: (slept.append(s),
                                                                    now.__setitem__(0, now[0] + s)))
    for _ in range(3):
        lim.wait()
    assert slept == []
    lim.wait()
    assert slept and 59.0 < slept[0] <= 60.1


def test_rules_arm_matches_the_step1_policy(ctx, toolbox, tmp_path):
    out = _runner(ctx, toolbox, None, tmp_path, arm="rules").run()[0]
    c = ctx.candidates[0]
    a, b = ctx.required_span(c)
    dec, _, _ = rules_decision(ctx.evidence(c), ctx.evidence(c, ctx.reanalyse_tactics(a, b)),
                               ctx.vcfg)
    assert out.decision == dec and out.decided_by == "rules" and out.llm_calls == 0


def test_real_client_request_format_on_stubber(ctx, toolbox, tmp_path):
    """The loop's Converse requests pass botocore's service-model validation."""
    raw = boto3.client("bedrock-runtime", region_name="ap-southeast-2",
                       aws_access_key_id="testing", aws_secret_access_key="testing",
                       config=Config(retries={"total_max_attempts": 1}))
    client = BedrockClient(ctx.cfg, client=raw, log_path=tmp_path / "llm.jsonl",
                           sleep=lambda s: None)
    c, a, b = _span(ctx)

    def resp(name, args, i):
        return {"output": {"message": {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": f"t{i}", "name": name, "input": args}}]}},
            "stopReason": "tool_use",
            "usage": {"inputTokens": 1500, "outputTokens": 40, "totalTokens": 1540},
            "metrics": {"latencyMs": 5}}

    with Stubber(raw) as stub:
        steps = [("check_frame_quality", {"start_s": a, "end_s": b, "why": "q"}),
                 ("record_decision", {"event_id": c.id, "decision": "uncertain", "reason": "x",
                                      "citations": [{"ref": "R1"}]})]
        for i, (n, args) in enumerate(steps):
            stub.add_response("converse", resp(n, args, i),
                              {"modelId": ANY, "messages": ANY, "system": ANY,
                               "inferenceConfig": ANY, "toolConfig": ANY})
        out = _runner(ctx, toolbox, client, tmp_path).run()[0]
        stub.assert_no_pending_responses()
    assert (out.llm_calls, out.decision, out.decided_by) == (2, "uncertain", "agent")
    assert out.cost_usd > 0


# --------------------------------------------------------------------------- eval scoring


def _eval_module():
    spec = importlib.util.spec_from_file_location("eval_agent",
                                                  repo_path("scripts/eval_agent.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_eval_scoring_counts_alerts_by_candidate_label(vcfg):
    mod = _eval_module()
    from dataclasses import asdict
    good, bad = asdict(ev()), asdict(ev(reverted_after_s=30.0))
    run = {"match_id": "m", "gt": {"match_id": "m", "formations": [], "changes": [
        {"team": "home", "t": 1000.0, "from": "4-4-2", "to": "3-5-2"}]},
        "candidates": [
            {"id": "evt_001", "team": "home", "t": 1010.0, "detected_at_s": 1040.0,
             "from": "4-4-2", "to": "3-5-2", "first": good, "reanalysis": good},
            {"id": "evt_002", "team": "away", "t": 2000.0, "detected_at_s": 2030.0,
             "from": "4-3-3", "to": "4-2-3-1", "first": bad, "reanalysis": bad}]}
    one = mod.score([run], vcfg, "oneshot", 90.0)["summary"]
    rul = mod.score([run], vcfg, "rules", 90.0)["summary"]
    assert (one["alerted_hits"], one["false_alerts"]) == (1, 1)
    assert (rul["alerted_hits"], rul["false_alerts"], rul["rejected_fps"]) == (1, 0, 1)
    assert rul["mean_alert_delay_s"] == pytest.approx(1040.0 + vcfg.lookahead_s - 1000.0)


def test_final_seeds_need_the_final_flag():
    assert _eval_module().main(["--set", "final"]) == 2


def test_llm_arm_scoring_and_the_section_8_judgement(vcfg):
    mod = _eval_module()
    from dataclasses import asdict
    good = asdict(ev())
    run = {"match_id": "m", "gt": {"match_id": "m", "formations": [], "changes": [
        {"team": "home", "t": 1000.0, "from": "4-4-2", "to": "3-5-2"}]},
        "candidates": [{"id": "evt_001", "team": "home", "t": 1010.0, "detected_at_s": 1040.0,
                        "from": "4-4-2", "to": "3-5-2", "first": good, "reanalysis": good}]}
    rows = {("m", "evt_001"): {"decision": "uncertain", "verdict": "confirm", "reason": "r",
                               "decided_by": "agent", "tool_calls": ["check_frame_quality"]}}
    s = mod.score([run], vcfg, "llm", 90.0, rows)["summary"]
    assert (s["alerted_hits"], s["uncertain_hits"]) == (0, 1)
    with pytest.raises(KeyError):
        mod.score([run], vcfg, "llm", 90.0, {})

    def summ(fa, hits, unc=0.1, delay=100.0):
        return {"false_alerts": fa, "alerted_hits": hits, "uncertain_share": unc,
                "mean_alert_delay_s": delay}

    assert mod.judge(summ(16, 30))["verdict"] == "helped"
    assert mod.judge(summ(16, 30, unc=0.31))["verdict"] == "partial"
    assert mod.judge(summ(17, 31))["verdict"] == "partial"
    assert mod.judge(summ(26, 34))["verdict"] == "did not help"
    assert mod.judge(summ(17, 28))["verdict"] == "did not help"  # no better than the config
    assert mod.llm_adds(summ(10, 30), summ(12, 30))
    assert not mod.llm_adds(summ(11, 30), summ(12, 30))
    assert not mod.llm_adds(summ(10, 29), summ(12, 30))  # fewer FAs but lost a hit
