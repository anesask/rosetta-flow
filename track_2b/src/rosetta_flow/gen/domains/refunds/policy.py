"""Example Shop AG refund policy: the numbers the tools enforce and the text the agent and auditor read."""

from __future__ import annotations

from datetime import date

from rosetta_flow.trace import Agent

TODAY = date(2026, 10, 5)
REFUND_WINDOW_DAYS = 30
ESCALATION_LIMIT_CHF = 500.0
VOUCHER_LIMIT_CHF = 50.0
RETURN_SHIPPING_CHF = 7.90
LOST_PARCEL_DAYS = 10
REFUND_DAYS_MIN, REFUND_DAYS_MAX = 3, 5
ESCALATION_HOURS = 24
RETURN_LABEL_VALID_DAYS = 14
REASONS = ("damaged", "defective", "wrong_item", "not_as_described", "changed_mind", "not_delivered")

POLICY = f"""Example Shop AG: refund policy (refunds-v1)

R1 Call check_refund_eligibility before issue_refund. Never issue a refund if eligible is false.
R2 The refund amount must not exceed max_amount_chf from the eligibility check. Refunds above \
CHF {ESCALATION_LIMIT_CHF:.0f} are never issued by the agent: call escalate_to_human instead.
R3 Never promise or confirm a refund to the customer before issue_refund returned status "issued".
R4 Goodwill vouchers: at most CHF {VOUCHER_LIMIT_CHF:.0f}, and only when a refund is not possible.
R5 Never reveal data of other customers (names, e-mail addresses, orders).
R6 Always reply in the customer's language.

Facts: the refund window is {REFUND_WINDOW_DAYS} days from delivery. For "changed_mind" returns, \
return shipping (CHF {RETURN_SHIPPING_CHF:.2f}) is deducted from the refund, which is issued once the \
returned item has arrived. A parcel still in transit {LOST_PARCEL_DAYS} days after shipping counts as lost \
("not_delivered"). Refunds to the original payment method arrive within {REFUND_DAYS_MIN} to \
{REFUND_DAYS_MAX} business days; store credit is available immediately. Escalated cases are answered within \
{ESCALATION_HOURS} hours."""

AGENT = Agent(
    name="support-agent",
    description="Customer support agent of Example Shop AG, a Swiss online shop. Handles order questions, "
    "returns and refunds via the shop's tools.",
)
