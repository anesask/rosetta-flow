"""Simulator and scripted agent against fake models that misbehave the ways real ones do. No network."""

import json

import pytest
from fakes import call, customer, resp, scripted_models

from rosetta_flow import llm
from rosetta_flow.batch import run_batch
from rosetta_flow.gen import simulate as sim
from rosetta_flow.gen.domains import DOMAINS
from rosetta_flow.gen.numbers import unsupported_numbers
from rosetta_flow.gen.scripted import VerbalizationError
from rosetta_flow.llm import LLMConfig
from rosetta_flow.trace import Domain, SpanKind, Trace, check_label, read_jsonl

SPEC = DOMAINS[Domain.REFUNDS]
CFG = LLMConfig(name="fake", base_url="http://fake", api_key="x")


def fake_llm_agent(mode):
    def chat(cfg, messages, model=None, **kw):
        if "tools" not in kw:
            return customer(messages)
        if mode == "loop":
            return resp(tool_calls=[call("get_customer", '{"customer_id": "C-1"}')])
        if messages[-1]["role"] == "user":  # fresh customer message: broken tool calls first
            return resp(
                "Ich schaue nach.",
                [call("nuke_database", "{}", 0), call("get_order", "{oops", 1), call("get_order", "[1, 2]", 2)],
            )
        return resp("Leider konnte ich nichts finden.")

    return chat


def fake_scripted_models(bad_first_draft=True):
    return scripted_models(bad_first_draft=bad_first_draft, with_numbers=False)


def test_llm_agent_survives_broken_tool_calls_and_labels_safely(monkeypatch):
    monkeypatch.setattr(llm, "chat", fake_llm_agent("broken"))
    r = sim.simulate_one(SPEC, CFG, seed=1, index=0, agent="llm")
    Trace.model_validate(r.trace.model_dump())
    results = [s for s in r.trace.spans if s.kind is SpanKind.TOOL_RESULT]
    assert [s.status for s in results] == ["error"] * 6
    assert "unknown tool" in results[0].result and "not valid JSON" in results[1].result
    assert r.meta["stop_reason"] == "customer_ended"  # lowercase [end] recognised
    assert r.label is not None and r.label.source == "clean"
    check_label(r.trace, r.label)

    monkeypatch.setattr(llm, "chat", fake_llm_agent("loop"))
    r = sim.simulate_one(SPEC, CFG, seed=1, index=0, agent="llm")
    assert r.meta["stop_reason"] == "agent_tool_loop" and r.label is None  # cut-off runs are never labelled


def test_scripted_agent_is_policy_clean_across_scenarios(monkeypatch):
    monkeypatch.setattr(llm, "chat", fake_scripted_models())
    intents, tools_used = set(), set()
    for i in range(40):
        r = sim.simulate_one(SPEC, CFG, seed=11, index=i, agent="scripted")
        assert r.label is not None and r.label.source == "clean", (r.meta["scenario"]["intent"], r.meta["violations"])
        calls = [s for s in r.trace.spans if s.kind is SpanKind.TOOL_CALL]
        names = [c.tool for c in calls]
        if "issue_refund" in names:  # R1 by construction: the check comes first
            assert "check_refund_eligibility" in names[: names.index("issue_refund")]
        retried = [s for s in r.trace.spans if s.kind is SpanKind.TOOL_RESULT and s.status == "error"]
        assert all("timeout" in s.result for s in retried)  # the only errors are injected, retried timeouts
        intents.add(r.meta["scenario"]["intent"])
        tools_used.update(names)
    assert len(intents) >= 6
    assert {"check_refund_eligibility", "issue_refund", "escalate_to_human", "get_shipping_status"} <= tools_used


def test_verbalizer_rejects_invented_numbers_and_gives_up_cleanly(monkeypatch):
    monkeypatch.setattr(llm, "chat", fake_scripted_models())
    r = sim.simulate_one(SPEC, CFG, seed=11, index=0, agent="scripted")
    assert r.meta["usage"]["rejected_drafts"] >= 1
    assert all("999" not in (s.text or "") for s in r.trace.spans if s.kind is SpanKind.AGENT_MESSAGE)

    def always_bad(cfg, messages, model=None, **kw):
        if messages[0]["content"].startswith("You write the next chat message"):
            return resp("Sie erhalten CHF 999 zurück.")
        return fake_scripted_models(bad_first_draft=False)(cfg, messages, model, **kw)

    monkeypatch.setattr(llm, "chat", always_bad)
    with pytest.raises(VerbalizationError):
        sim.simulate_one(SPEC, CFG, seed=11, index=0, agent="scripted")


def test_number_check_understands_swiss_formats():
    facts = {"amount": 1258.9, "order": "A-7731", "delivered": "2026-09-05", "days": {"min": 3, "max": 5}}
    ok = "Bestellung A-7731 vom 05.09.2026: CHF 1'258.90 bzw. 1’258,90, Gutschrift in 3 bis 5 Tagen."
    assert unsupported_numbers(ok, facts) == []
    assert unsupported_numbers("CHF 1'259.00", facts) == ["1'259.00"]
    assert unsupported_numbers("am 06.09.2026", facts) == ["06.09.2026"]
    assert unsupported_numbers("innert 24 Stunden", facts) == ["24"]


def test_batch_survives_failures_and_resumes(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "chat", fake_llm_agent("broken"))
    original, attempts = sim.simulate_one, []

    def flaky(spec, cfg, seed, index, model=None, agent="llm"):
        attempts.append(index)
        if index == 1 and attempts.count(1) == 1:
            raise RuntimeError("API hiccup")
        return original(spec, cfg, seed, index, model, agent)

    monkeypatch.setattr(sim, "simulate_one", flaky)
    kw = {"n": 3, "seed": 1, "out": tmp_path, "workers": 2, "model": None, "agent": "llm"}
    m = sim.run(SPEC, CFG, **kw)
    assert m["succeeded"] == 2 and len(m["failures"]) == 1

    with pytest.raises(SystemExit, match="--resume"):
        sim.run(SPEC, CFG, **kw)

    with (tmp_path / sim.PROGRESS).open("a", encoding="utf-8") as f:
        f.write('{"trace": {"trace_id": "half-written')  # crash mid-line
    m = sim.run(SPEC, CFG, **kw, resume=True)
    assert m["succeeded"] == 3 and not m["failures"]
    assert sorted(attempts) == [0, 1, 1, 2]  # only the failed run was redone
    traces = list(read_jsonl(tmp_path / "traces.jsonl", Trace))
    assert [t.trace_id for t in traces] == ["refunds-1-0000", "refunds-1-0001", "refunds-1-0002"]
    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))["labels"] == {"clean": 3}


def test_token_budget_stops_new_work_and_resume_continues(tmp_path):
    started = []

    def work(i):
        started.append(i)
        return {"key": i, "tokens": 1000}

    kw = {"to_record": lambda r: r, "key_of": lambda rec: rec["key"], "tokens_of": lambda rec: rec["tokens"]}
    first = run_batch(range(20), work, tmp_path / "p.jsonl", workers=2, max_tokens=5000, **kw)
    assert first.stopped_by_budget and 5 <= len(first.done) <= 7 and len(started) == len(first.done)
    rest = run_batch(range(20), work, tmp_path / "p.jsonl", workers=2, resume=True, **kw)
    assert not rest.stopped_by_budget and len(rest.done) == 20 and len(started) == 20  # nothing done twice


def test_verbalizer_never_invents_a_name_or_gender():
    from types import SimpleNamespace as NS

    from rosetta_flow.gen.scripted import ScriptedAgent

    agent = ScriptedAgent.__new__(ScriptedAgent)
    agent.spans = [NS(kind=SpanKind.USER_MESSAGE, text="Bonjour, c'est Olivier Girard, superviseur.")]
    invented = {"Hi Thomas, the part is out.": "Thomas", "Bonjour Madame, la jauge est expirée.": "Madame"}
    fine = ["Bonjour Monsieur Girard, le lot reste bloqué.", "Buongiorno Olivier, tutto ok.", "Hello there, all good.",
            "Bonjour, la cote de 8,07 mm est conforme."]  # fmt: skip
    assert {d: agent._invented_address(d) for d in invented} == invented
    assert not any(agent._invented_address(d) for d in fine)
    assert agent._invented_address("Merci pour votre suivi, Anna.") == "Anna"
    assert sim._strip_end("Verstanden, ich warte. [IN PROGRESS] [end]") == ("Verstanden, ich warte.", True)


def test_greeting_repair_removes_only_greeting_and_name():
    from rosetta_flow.gen.scripted import strip_greeting

    assert strip_greeting("Guten Tag, Sarah Schmid. Die Messung ist ungültig.") == "Die Messung ist ungültig."
    assert strip_greeting("Bonjour Monsieur Girard, le lot reste bloqué.") == "Le lot reste bloqué."
    assert strip_greeting("Guten Tag, die Messung ist ungültig.") == "Die Messung ist ungültig."  # content kept
