"""Manufacturing domain offline: world and scenarios agree, the scripted agent is policy-clean on every intent,
and every plant injector plants exactly the violation the checker would report at the labelled spans."""

import json
import random
import re

from fakes import REPLIES, resp

from rosetta_flow import llm
from rosetta_flow.gen import simulate as sim
from rosetta_flow.gen.domains import DOMAINS
from rosetta_flow.gen.domains.manufacturing.injectors import PLANT_INJECTORS
from rosetta_flow.gen.domains.manufacturing.scenarios import INTENT_WEIGHTS
from rosetta_flow.gen.inject import Job
from rosetta_flow.llm import LLMConfig
from rosetta_flow.trace import Domain, SpanKind

SPEC = DOMAINS[Domain.MANUFACTURING]
CFG = LLMConfig(name="fake", base_url="http://fake", api_key="x")
_FACT = re.compile(r"^- (\w+): (.*)$", re.MULTILINE)


def plant_models():
    """Requester states its facts, the reader extracts them, the verbaliser answers without numbers."""

    def chat(cfg, messages, model=None, **kw):
        system = messages[0]["content"]
        if "response_format" in kw:
            name = kw["response_format"]["json_schema"]["name"]
            text = messages[-1]["content"]
            if name == "CharacteristicRead":
                listing = dict(re.findall(r"(C\d) = ([^;.]+)", system))
                return resp(json.dumps({"characteristic": next((k for k, v in listing.items() if v in text), None)}))
            facts = dict(re.findall(r"(\w+)=(\S+)", text))
            return resp(json.dumps({
                "topic": "other", "work_order_id": facts.get("work_order_id"), "lot_id": facts.get("lot_id"),
                "machine_id": facts.get("machine_id"), "gauge_id": facts.get("gauge_id"),
                "measured_mm": facts.get("measured_mm"),
                "unit_number": int(facts["unit_number"]) if "unit_number" in facts else None,
                "characteristic_words": facts.get("characteristic", "").replace("_", " ") or None,
                "pushes_back": False,
            }))  # fmt: skip
        if system.startswith("You write the next chat message"):
            lang = next(k for k, name in REPLIES.items() if f"Language: {name[0]}" in system)
            return resp(REPLIES[lang][1])
        if sum(m["role"] == "assistant" for m in messages):
            return resp("Merci [end]")
        facts = {k: v.replace(" ", "_") for k, v in _FACT.findall(system)}
        return resp(" ".join(f"{k}={v}" for k, v in facts.items()))

    return chat


def test_world_and_scenarios_agree():
    w = SPEC.make_world(5)
    assert SPEC.make_world(5).work_orders.keys() == w.work_orders.keys()  # deterministic
    seen = set()
    for seed in range(200):
        world = SPEC.make_world(seed)
        s = SPEC.sample_scenario(world, random.Random(seed))
        seen.add(s.intent)
        if s.intent.startswith(("measurement", "gauge")):
            wo = world.work_orders[s.facts["work_order_id"]]
            rev = world.parts[wo.part_no].revision(wo.revision)
            c = next(c for c in rev.characteristics if c.name == s.facts["characteristic"])
            value, gauge = float(s.facts["measured_mm"]), world.gauges[s.facts["gauge_id"]]
            assert int(s.facts["unit_number"]) == wo.qty_made
            assert (gauge.status == "valid") == (s.intent != "gauge_invalid")
            if s.intent == "measurement_ok":
                assert c.within(value)
            elif s.intent == "measurement_out":
                assert not c.within(value)
    assert seen == set(INTENT_WEIGHTS)


def test_scripted_agent_is_policy_clean_on_every_intent(monkeypatch):
    monkeypatch.setattr(llm, "chat", plant_models())
    by_intent: dict[str, list[str]] = {}
    for i in range(60):
        r = sim.simulate_one(SPEC, CFG, seed=21, index=i, agent="scripted")
        intent = r.meta["scenario"]["intent"]
        assert r.label is not None and r.label.source == "clean", (intent, r.meta["violations"])
        by_intent[intent] = [s.tool for s in r.trace.spans if s.kind is SpanKind.TOOL_CALL]
    assert len(by_intent) == len(INTENT_WEIGHTS)
    out = by_intent["measurement_out"]
    steps = ["get_gauge_status", "record_inspection", "get_inspection_records", "create_ncr", "place_hold",
             "request_disposition"]  # fmt: skip
    assert [t for t in out if t in steps] == steps
    assert (
        "record_inspection" not in by_intent["gauge_invalid"] and "request_remeasurement" in by_intent["gauge_invalid"]
    )
    assert "release_lot" in by_intent["release_approved"]
    assert "release_lot" not in by_intent["release_pending"] + by_intent["release_blocked"]
    assert "request_first_article_check" in by_intent["restart_long_stop"]
    assert "request_tool_change" in by_intent["tool_worn"]
    assert not [t for t in by_intent["restart_short_stop"] if t.startswith("request_")]


def test_plant_injectors_plant_what_the_checker_reports(monkeypatch):
    monkeypatch.setattr(llm, "chat", plant_models())
    traces = [sim.simulate_one(SPEC, CFG, seed=31, index=i, agent="scripted") for i in range(60)]
    rule = {"release_without_approval": "Q4", "wrong_revision": "Q2", "scope_too_small": "Q3",
            "too_few_first_pieces": "Q6"}  # fmt: skip
    for inj in PLANT_INJECTORS:
        fitting = [r for r in traces if inj.applicable(r.trace, SPEC)]
        assert fitting, inj.name
        # Injectors decline traces they cannot edit cleanly (e.g. limits that differ between revisions).
        tried = ((r, SPEC.make_world(r.meta["world_seed"])) for r in fitting)
        r, world, injection = next(
            ((r, w, done) for r, w in tried if (done := inj.apply(Job(r.trace, SPEC, random.Random(1), None, w)))),
            (None, None, None),
        )
        assert injection is not None, inj.name
        broken, _ = r.trace.with_spans(injection.spans)
        old_to_new = {s.id: n.id for s, n in zip(injection.spans, broken.spans, strict=True)}
        labelled = {old_to_new[x] for x in injection.span_ids}
        found = [v for v in SPEC.check(broken, world) if v.certain and v.rule == rule[inj.name]]
        assert any(labelled & set(v.span_ids) for v in found), (inj.name, injection.note, found)
