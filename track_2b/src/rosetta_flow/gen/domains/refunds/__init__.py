"""Refunds domain: Example Shop AG, e-commerce customer support (fictional).

policy.py     numbers and policy text      world.py     seeded customers, catalogue, orders
tools.py      the 8 shop tools             scenarios.py what simulated customers want
checker.py    policy checker               agent.py     scripted dialogue manager (imported by the simulator)
"""

from rosetta_flow.gen.domains.base import DomainSpec
from rosetta_flow.gen.domains.refunds.checker import check
from rosetta_flow.gen.domains.refunds.flavour import invented_fact, leak
from rosetta_flow.gen.domains.refunds.policy import AGENT, POLICY, TODAY
from rosetta_flow.gen.domains.refunds.scenarios import sample_scenario
from rosetta_flow.gen.domains.refunds.tools import TOOLS
from rosetta_flow.gen.domains.refunds.world import RefundsWorld, make_world
from rosetta_flow.trace import Domain

SPEC: DomainSpec[RefundsWorld] = DomainSpec(
    domain=Domain.REFUNDS,
    policy_id="refunds-v1",
    policy=POLICY,
    agent=AGENT,
    tools=TOOLS,
    make_world=make_world,
    check=check,
    sample_scenario=sample_scenario,
    today=TODAY,
    guards={"issue_refund": "check_refund_eligibility"},
    action_failures={
        "issue_refund": "payment provider unavailable (503): refund not created, retry later",
        "create_return_label": "label service unavailable: no label created",
        "apply_voucher": "voucher service timeout: no voucher created",
        "escalate_to_human": "ticket system unavailable: case not queued",
    },
    requester="a customer chatting with the support of Example Shop AG, a Swiss online shop",
    invented_fact=invented_fact,
    leak=leak,
)

__all__ = ["SPEC"]
