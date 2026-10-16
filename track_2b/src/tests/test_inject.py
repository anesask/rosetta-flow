"""Error injectors on offline-simulated traces: exact labels, minimal edits, no give-aways. No network."""

import random
from collections import Counter
from types import SimpleNamespace as NS

import pytest
from fakes import scripted_models

from rosetta_flow import llm
from rosetta_flow.gen import simulate as sim
from rosetta_flow.gen.domains import DOMAINS
from rosetta_flow.gen.domains.refunds.world import make_world
from rosetta_flow.gen.inject import Job, apply, injectors_for, plan, rewrite
from rosetta_flow.gen.numbers import number_values
from rosetta_flow.llm import LLMConfig, LLMContext
from rosetta_flow.trace import Domain, ErrorType, SpanKind, Trace

SPEC = DOMAINS[Domain.REFUNDS]
CFG = LLMConfig(name="fake", base_url="http://fake", api_key="x")
INJECTORS = {i.name: i for i in injectors_for(Domain.REFUNDS)}


@pytest.fixture(scope="module")
def traces() -> list[Trace]:
    mp = pytest.MonkeyPatch()
    mp.setattr(llm, "chat", scripted_models())
    try:
        return [sim.simulate_one(SPEC, CFG, seed=5, index=i, agent="scripted").trace for i in range(40)]
    finally:
        mp.undo()


def _calls(t):
    return [s for s in t.spans if s.kind is SpanKind.TOOL_CALL]


def _certain_rules(t):
    return {v.rule for v in SPEC.check(t, make_world(0)) if v.certain}


def test_code_injectors_make_exactly_the_labelled_change(traces):
    applied = Counter()
    for idx, original in enumerate(traces):
        for name, inj in INJECTORS.items():
            if inj.needs_llm or not inj.applicable(original, SPEC):
                continue
            new, label, _ = apply(Job(original, SPEC, random.Random(idx), None), inj)
            applied[name] += 1
            (err,) = label.errors
            assert err.type is inj.error_type and label.source == "injected", name
            assert [c.call_id for c in _calls(new)] == [f"c{i + 1}" for i in range(len(_calls(new)))], name
            Trace.model_validate(new.model_dump())

            before = {s.model_dump_json(exclude={"id", "call_id", "start_ms", "end_ms"}) for s in original.spans}
            after = {s.model_dump_json(exclude={"id", "call_id", "start_ms", "end_ms"}) for s in new.spans}
            changed = after - before
            starts = [s.start_ms or 0 for s in new.spans]
            assert starts == sorted(starts), name  # an edit must not show in the timing
            tools = lambda t: [c.tool for c in _calls(t)]  # noqa: E731
            if name == "contradicts_tool_result":
                assert len(changed) == 1 and number_values(next(iter(changed))) != number_values(""), name
                kinds = {new.span(sid).kind for sid in err.span_ids}
                assert kinds == {SpanKind.TOOL_RESULT, SpanKind.AGENT_MESSAGE}, name
            elif name == "ignored_tool_error":
                assert len(changed) == 1 and new.span(err.span_ids[0]).status == "error", name
            elif name in ("skipped_required_step", "false_completion"):
                assert not changed and len(new.spans) < len(original.spans), name
                assert "R1" in _certain_rules(new) or name == "false_completion", name
            elif name == "wrong_order":
                assert not changed and sorted(tools(new)) == sorted(tools(original)), name
                assert tools(new).index("issue_refund") < tools(new).index("check_refund_eligibility"), name
            elif name == "wrong_tool_args":
                assert len(changed) == 1 and SpanKind.TOOL_CALL in {new.span(s).kind for s in err.span_ids}, name
            elif name == "voucher_over_limit":
                assert "R4" in _certain_rules(new), name
    assert {"contradicts_tool_result", "ignored_tool_error", "false_completion", "wrong_tool_args"} <= set(applied)


def test_plan_balances_error_types_and_respects_rate(traces):
    code = [i for i in INJECTORS.values() if not i.needs_llm]
    plans = plan(traces * 5, SPEC, code, rate=0.5, seed=1)
    firsts = Counter(p[0] for p in plans if p)
    assert 0.35 < sum(bool(p) for p in plans) / len(plans) < 0.65
    # contradictions are possible in almost every trace; balancing must still keep any one type from dominating
    assert max(firsts.values()) / sum(firsts.values()) < 0.3 and len(firsts) >= 5


def test_llm_rewrites_are_accepted_only_when_verified(monkeypatch):
    original = "Ihre Rückerstattung von CHF 129.90 wird in 3 bis 5 Tagen gutgeschrieben, vielen Dank für Ihre Geduld."
    drafts = iter(
        [
            original,  # unchanged
            "Ihre Rückerstattung wird bald gutgeschrieben, es fällt eine Gebühr von CHF 4.90 an.",  # lost numbers
            "Your refund of CHF 129.90 arrives in 3 to 5 days; a fee of CHF 4.90 applies, thank you.",  # wrong language
            original[:-1] + " Es fällt eine Bearbeitungsgebühr von CHF 4.90 an.",  # good
        ]
    )
    monkeypatch.setattr(
        llm, "chat", lambda *a, **k: NS(choices=[NS(message=NS(content=next(drafts), tool_calls=None))], usage=None)
    )
    ctx = LLMContext(CFG)
    args = (original, "de", "Add a fee of CHF 4.90.")
    assert rewrite(ctx, *args, must_contain=("4.90",)) is None  # three bad drafts in a row: rejected
    assert "4.90" in rewrite(ctx, *args, must_contain=("4.90",))  # the fourth (good) draft on the next call


def test_acceptable_types_cover_genuine_overlaps():
    assert ErrorType.SKIPPED_REQUIRED_STEP in INJECTORS["wrong_tool_args"].acceptable
    assert ErrorType.FALSE_COMPLETION in INJECTORS["ignored_tool_error"].acceptable
    assert INJECTORS["data_leak"].acceptable == ()  # no overlap: must be named exactly
