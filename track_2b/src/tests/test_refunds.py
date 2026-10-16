import json
import math
import random
from datetime import timedelta

import pytest

from rosetta_flow.gen.domains import DOMAINS
from rosetta_flow.gen.domains.refunds import checker, policy, scenarios, tools, world
from rosetta_flow.trace import Domain, ErrorType, Span, SpanKind, Trace

SPEC = DOMAINS[Domain.REFUNDS]


def _order(oid, cid, delivered_days_ago, price=129.90, shipped_days_ago=None):
    shipped = policy.TODAY - timedelta(
        days=shipped_days_ago if shipped_days_ago is not None else delivered_days_ago + 2
    )
    delivered = policy.TODAY - timedelta(days=delivered_days_ago) if delivered_days_ago is not None else None
    return world.Order(
        oid, cid, [world.Item("HP-BT", "Bluetooth-Kopfhörer", 1, price)], shipped - timedelta(days=1),
        "delivered" if delivered else "in_transit", shipped, delivered, f"EX{oid[-4:]}CH",
    )  # fmt: skip


def _world() -> world.RefundsWorld:
    w = world.make_world(7)
    cid = next(iter(w.customers))
    w.orders |= {
        "A-0001": _order("A-0001", cid, delivered_days_ago=10),
        "A-0002": _order("A-0002", cid, delivered_days_ago=41),
        "A-0003": _order("A-0003", cid, delivered_days_ago=5, price=649.0),
        "A-0004": _order("A-0004", cid, delivered_days_ago=None, shipped_days_ago=15),
    }
    return w


@pytest.fixture
def shop() -> world.RefundsWorld:
    return _world()


class _T:
    """Builds a valid trace step by step, running tools against the world like the simulator does."""

    def __init__(self, world, language="de"):
        self.world, self.language, self.spans, self.n = world, language, [], 0

    def _add(self, **kw):
        self.spans.append(Span(id=f"{len(self.spans):03d}", **kw))
        return self

    def user(self, text):
        return self._add(kind=SpanKind.USER_MESSAGE, text=text)

    def agent(self, text):
        return self._add(kind=SpanKind.AGENT_MESSAGE, text=text)

    def tool(self, name, **args):
        self.n += 1
        status, result = SPEC.call(self.world, name, args)
        self._add(kind=SpanKind.TOOL_CALL, tool=name, args=args, call_id=f"c{self.n}")
        return self._add(kind=SpanKind.TOOL_RESULT, call_id=f"c{self.n}", status=status, result=result)

    def build(self) -> Trace:
        return Trace(trace_id="t", domain=Domain.REFUNDS, language=self.language, agent=policy.AGENT,
                     policy_id="refunds-v1", spans=self.spans)  # fmt: skip


def test_world_is_deterministic_multilingual_and_scenarios_fit_it():
    a = world.make_world(42)
    assert a.customers == world.make_world(42).customers and a.orders == world.make_world(42).orders
    assert world.make_world(43).orders != a.orders
    assert {c.language for c in world.make_world(1).customers.values()} == {"de", "fr", "it", "en"}
    fr = {n["fr"] for _, _, n in world.CATALOGUE}
    for o in a.orders.values():
        if a.customers[o.customer_id].language == "fr":
            assert all(i.name in fr for i in o.items)

    intents = set()
    for i in range(300):
        s = scenarios.sample_scenario(a, random.Random(i))
        o = a.orders[s.facts["order_id"]]
        assert o.customer_id == s.customer_id and a.customers[s.customer_id].language == s.language
        e = tools.eligibility(a, o, "not_delivered" if s.intent.startswith("parcel") else "damaged")
        expected = {"problem_in_window": True, "problem_late": False, "parcel_lost": True, "parcel_late": False,
                    "already_refunded": False, "big_refund": True}  # fmt: skip
        if s.intent in expected:
            assert e["eligible"] is expected[s.intent], s
        intents.add(s.intent)
    assert len(intents) == len(scenarios.INTENT_WEIGHTS)


def test_eligibility_rules(shop):
    def e(oid, reason="damaged"):
        r = tools.eligibility(shop, shop.orders[oid], reason)
        return r["eligible"], r["reason"], r["max_amount_chf"]

    assert e("A-0001") == (True, "within_window", 129.90)
    assert e("A-0001", "changed_mind") == (True, "within_window", pytest.approx(129.90 - policy.RETURN_SHIPPING_CHF))
    assert e("A-0002") == (False, "outside_window", 0.0)
    assert e("A-0004", "not_delivered") == (True, "parcel_lost", 129.90)
    assert e("A-0001", "not_delivered") == (False, "parcel_delivered", 0.0)
    shop.orders["A-0001"].refunded_chf = 129.90
    assert e("A-0001") == (False, "already_refunded", 0.0)


def test_tools_turn_bad_input_into_errors_and_trust_the_agent(shop):
    ok = SPEC.call(shop, "issue_refund", {"order_id": "A-0002", "amount_chf": 50, "method": "original_payment"})
    assert ok[0] == "ok"  # outside the window, still goes through: compliance is the agent's job
    errors = {
        "unknown tool": ("delete_everything", {}),
        "missing arg": ("check_refund_eligibility", {"order_id": "A-0001"}),
        "unknown arg": ("get_order", {"order_id": "A-0001", "force": True}),
        "unknown reason": ("check_refund_eligibility", {"order_id": "A-0001", "reason": "because"}),
        "over balance": ("issue_refund", {"order_id": "A-0002", "amount_chf": 100, "method": "store_credit"}),
        "bad method": ("issue_refund", {"order_id": "A-0001", "amount_chf": 10, "method": "cash"}),
        "text amount": ("apply_voucher", {"customer_id": "C-1", "amount_chf": "abc"}),
    }
    for amount in ("nan", "inf", float("nan"), -5, 0, True, None, [1]):
        errors[f"amount {amount!r}"] = ("issue_refund", {"order_id": "A-0001", "amount_chf": amount,
                                                        "method": "original_payment"})  # fmt: skip
    for name, (tool, args) in errors.items():
        status, msg = SPEC.call(shop, tool, args)
        assert status == "error" and isinstance(msg, str), name
    assert shop.orders["A-0001"].refunded_chf == 0  # none of the bad refunds touched the balance
    assert SPEC.call(shop, "get_order", {"order_id": " a-0001 "})[0] == "ok"

    schema = {t["function"]["name"]: t["function"]["parameters"] for t in SPEC.openai_tools()}
    assert len(schema) == 8 and not schema["issue_refund"]["additionalProperties"]


def test_tool_fuzz_never_raises_and_keeps_balances_sane(shop):
    rng = random.Random(0)
    junk = [None, True, -1, 0, 1e308, float("nan"), "", "A-0001", "a-0001", "C-1", "∞", "１２", [], {}, "x" * 10_000]
    junk += list(shop.orders)[:5] + list(shop.customers)[:3]
    for _ in range(3000):
        tool = rng.choice([*SPEC.tools, "nope"])
        params = list(SPEC.tools[tool].params) if tool in SPEC.tools else ["x"]
        args = {p: rng.choice([*junk, rng.uniform(-50, 900)]) for p in params if rng.random() < 0.9}
        status, result = SPEC.call(shop, tool, args)
        assert status in ("ok", "error")
        json.dumps(result, allow_nan=False)
    for o in shop.orders.values():
        assert math.isfinite(o.refunded_chf) and 0 <= o.refunded_chf <= o.amount_chf + 1e-9


def test_checker_flags_exactly_the_broken_rule():
    cid = _world().orders["A-0001"].customer_id
    other = next(c for c in _world().customers.values() if c.id != cid)
    # each case runs its tools against its own fresh world; refunds in one case must not leak into the next
    cases = {
        "clean refund": (
            _T(_world()).user("Kopfhörer kaputt, A-0001.").tool("get_order", order_id="A-0001")
            .tool("check_refund_eligibility", order_id="A-0001", reason="damaged")
            .tool("issue_refund", order_id="A-0001", amount_chf=129.90, method="original_payment")
            .agent("Danke. Die Rückerstattung von CHF 129.90 wurde veranlasst."), []),
        "clean denial": (
            _T(_world()).tool("check_refund_eligibility", order_id="A-0002", reason="damaged")
            .agent("Leider ist die Bestellung ausserhalb der Frist und kann nicht erstattet werden."), []),
        "refund without check": (
            _T(_world()).tool("issue_refund", order_id="A-0001", amount_chf=20, method="original_payment"),
            [("R1", ErrorType.SKIPPED_REQUIRED_STEP)]),
        "refund when not eligible": (
            _T(_world()).tool("check_refund_eligibility", order_id="A-0002", reason="damaged")
            .tool("issue_refund", order_id="A-0002", amount_chf=129.90, method="original_payment"),
            [("R1", ErrorType.POLICY_VIOLATION)]),
        "over max and over escalation limit": (
            _T(_world()).tool("check_refund_eligibility", order_id="A-0003", reason="changed_mind")
            .tool("issue_refund", order_id="A-0003", amount_chf=649.0, method="original_payment"),
            [("R2", ErrorType.POLICY_VIOLATION)] * 2),
        "voucher too high while refund possible": (
            _T(_world()).tool("check_refund_eligibility", order_id="A-0001", reason="damaged")
            .tool("apply_voucher", customer_id=cid, amount_chf=80),
            [("R4", ErrorType.POLICY_VIOLATION)] * 2),
        "other customer's email": (
            _T(_world()).tool("get_order", order_id="A-0001").agent(f"Bestellung gefunden. Kontakt: {other.email}"),
            [("R5", ErrorType.DATA_LEAK)]),
    }  # fmt: skip
    for name, (builder, expected) in cases.items():
        violations = checker.check(builder.build(), builder.world)
        assert sorted((v.rule, v.error_type) for v in violations) == sorted(expected), name
        assert all(v.certain for v in violations), name


def test_heuristic_rules_never_become_certain_labels(shop):
    promised = (
        _T(_world()).tool("check_refund_eligibility", order_id="A-0002", reason="damaged")
        .agent("Gute Nachricht! Ihre Rückerstattung von CHF 129.90 wurde genehmigt.").build()
    )  # fmt: skip
    wrong_lang = (
        _T(shop, "de")
        .user("Wo ist mein Paket?")
        .agent("Bonjour, malheureusement votre colis est encore en route, nous vous tenons au courant.")
        .build()
    )
    for trace, rule, kind in [
        (promised, "R3", ErrorType.CONTRADICTS_TOOL_RESULT),
        (wrong_lang, "R6", ErrorType.LANGUAGE_MISMATCH),
    ]:
        (v,) = checker.check(trace, shop)
        assert (v.rule, v.error_type, v.certain) == (rule, kind, False)
