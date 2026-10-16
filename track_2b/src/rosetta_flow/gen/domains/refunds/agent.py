"""Scripted support agent for Example Shop AG: a policy-correct dialogue manager over the refunds tools."""

from __future__ import annotations

import re
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from rosetta_flow.gen.domains.refunds import policy
from rosetta_flow.gen.domains.refunds.world import Order
from rosetta_flow.gen.scripted import ScriptedAgent

_ORDER_ID = re.compile(r"\bA-\d{4}\b", re.IGNORECASE)
_GOAL_TO_ISSUE = {"arrived damaged": "damaged", "does not work": "defective", "different product": "wrong_item"}


class CustomerRead(BaseModel):
    """What the agent understands from one customer message."""

    model_config = ConfigDict(extra="forbid")

    order_id: str | None
    issue: Literal[
        "damaged", "defective", "wrong_item", "changed_mind", "not_delivered", "where_is_parcel", "other", "unclear"
    ]
    wants: Literal["refund", "information", "compensation", "human", "nothing"]
    asks_refund_timing: bool
    pushes_back: bool


READ_INSTRUCTION = (
    "You analyse customer messages for the support system of a Swiss online shop. Read the latest customer message "
    "in the context of the conversation and fill the fields. order_id: only if the customer wrote an order number "
    "like A-1234, else null. issue: the customer's problem (damaged on arrival, defective/not working, wrong item "
    "received, changed their mind, parcel never arrived, asking where the parcel is). wants: what they ask for now. "
    "asks_refund_timing: they ask when or how the money comes back. pushes_back: they disagree with or complain "
    "about a decision the agent already gave."
)


class RefundsAgent(ScriptedAgent):
    NOTES: ClassVar[dict[str, tuple[str, ...]]] = {
        "lookup_orders": (
            "No order number in the message; looking up the customer's orders.",
            "Customer did not give an order id. Checking the account first.",
            "Need the order first. Listing orders on the account.",
        ),
        "check": (
            "Order {order} found. Checking eligibility (reason: {reason}) before promising anything.",
            "R1: eligibility check comes first. Reason looks like '{reason}'.",
            "Customer wants money back for {order}; verifying eligibility with reason {reason}.",
        ),
        "refund": (
            "Eligible, max CHF {amount}. Issuing the refund to the original payment method.",
            "Within the window and under the CHF 500 limit: refund CHF {amount}.",
        ),
        "escalate_amount": (
            "CHF {amount} is above the CHF 500 agent limit (R2): escalating instead of refunding.",
            "Refund would be CHF {amount}; R2 says escalate.",
        ),
        "denied": (
            "Not eligible ({reason}). No refund; explain why.",
            "Eligibility check says no: {reason}.",
        ),
        "parcel": (
            "Checking tracking for {tracking}.",
            "Customer asks about delivery. Looking at the tracking events.",
        ),
        "return": (
            "Change of mind within the window: return label, refund after the item is back minus CHF 7.90.",
            "changed_mind is eligible; creating the return label.",
        ),
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.order: Order | None = None
        self.seen_orders: set[str] = set()
        self.outcome: str | None = None
        self.refund: dict[str, Any] | None = None
        self.voucher_given = False
        self.escalated = False

    # entry point

    def respond(self, customer_text: str, customer_done: bool = False) -> str:
        if customer_done and self.outcome:
            return self.say("thank the customer briefly and close the conversation")
        read = self.read(CustomerRead, READ_INSTRUCTION, customer_text) or self._fallback_read(customer_text)

        if self.order is None and not self._find_order(read, customer_text):
            return self._last_agent_text()
        if read.wants == "human" and not self.escalated:
            return self._escalate("customer asked for a human colleague")
        if self.outcome is None:
            return self._handle_issue(read)
        if read.asks_refund_timing and self.refund:
            return self.say(
                "answer when the refunded money arrives",
                refund_amount_chf=self.refund["amount_chf"],
                method=self.refund["method"],
                business_days_min=policy.REFUND_DAYS_MIN,
                business_days_max=policy.REFUND_DAYS_MAX,
            )
        if read.pushes_back or read.wants == "compensation":
            if self.outcome == "denied" and not self.voucher_given:
                return self._voucher(lead="acknowledge the frustration and, since a refund is not possible, offer")
            if not self.escalated and self.outcome in ("denied", "voucher", "already_refunded"):
                return self._escalate("customer disagrees with the decision")
        return self.say(
            "briefly confirm the matter is handled as already explained and ask if there is anything else",
            **self._summary(),
        )

    # order resolution

    def _find_order(self, read: CustomerRead, text: str) -> bool:
        cid = self.scenario.customer_id
        given = read.order_id or (m.group() if (m := _ORDER_ID.search(text)) else None)
        if given:
            status, res = self.tool("get_order", order_id=given.strip().upper())
            if status == "ok" and res.get("customer_id") == cid:
                self._select(res["order_id"])
                return True
            # Unknown or someone else's (never reveal which, R5): fall back to the account, like a real agent would
            # instead of asking the customer to re-check the same number again and again.
            return self._list_account_orders(not_found=given)
        return self._list_account_orders()

    def _list_account_orders(self, not_found: str | None = None) -> bool:
        cid = self.scenario.customer_id
        self.note("lookup_orders")
        _, cust = self.tool("get_customer", customer_id=cid)
        ids = cust.get("orders", []) if isinstance(cust, dict) else []
        if len(ids) == 1:
            self._select(ids[0])
            return True
        details = []
        for oid in ids[:4]:
            status, o = self.tool("get_order", order_id=oid)
            if status == "ok":
                self.seen_orders.add(oid)
                details.append(
                    {"order_id": oid, "items": [i["name"] for i in o["items"]], "ordered_on": o["order_date"]}
                )
        if not_found:
            self.say(
                "say that the number the customer gave matches no order in their account, then list their orders "
                "and ask which one they mean",
                number_given=not_found,
                orders=details,
            )
        else:
            self.say("ask which of these orders the customer means", orders=details)
        return False

    def _select(self, order_id: str) -> None:
        self.order = self.world.orders[order_id]
        self.seen_orders.add(order_id)

    # issue handling

    def _handle_issue(self, read: CustomerRead) -> str:
        issue = read.issue if read.issue not in ("other", "unclear") else self._issue_from_scenario()
        assert self.order is not None
        if issue in ("where_is_parcel", "not_delivered") or self.order.status == "in_transit":
            return self._parcel_flow()
        if issue == "changed_mind":
            return self._return_flow()
        reason = issue if issue in ("damaged", "defective", "wrong_item") else "damaged"
        return self._refund_flow(reason, wants_compensation=read.wants == "compensation")

    def _issue_from_scenario(self) -> str:
        if self.scenario.intent.startswith("parcel"):
            return "where_is_parcel"
        if self.scenario.intent == "changed_mind":
            return "changed_mind"
        return next((v for k, v in _GOAL_TO_ISSUE.items() if k in self.scenario.goal), "damaged")

    def _maybe_lookup_order(self, p: float = 0.65) -> None:
        assert self.order is not None
        if self.order.id not in self.seen_orders and self.rng.random() < p:
            self.tool("get_order", order_id=self.order.id)
            self.seen_orders.add(self.order.id)

    def _eligibility(self, reason: str) -> dict[str, Any]:
        assert self.order is not None
        self.note("check", order=self.order.id, reason=reason)
        status, e = self.tool("check_refund_eligibility", order_id=self.order.id, reason=reason)
        if status != "ok":
            raise RuntimeError(f"eligibility check failed unexpectedly: {e}")
        return e

    def _refund_flow(self, reason: str, wants_compensation: bool) -> str:
        assert self.order is not None
        self._maybe_lookup_order()
        e = self._eligibility(reason)
        if e["eligible"]:
            return self._pay_out(e["max_amount_chf"], why="refund")
        return self._not_eligible(e, wants_compensation)

    def _pay_out(self, amount: float, why: str) -> str:
        assert self.order is not None
        if amount > policy.ESCALATION_LIMIT_CHF:
            self.note("escalate_amount", amount=f"{amount:.2f}")
            return self._escalate(
                f"refund of CHF {amount:.2f} for order {self.order.id} exceeds the CHF "
                f"{policy.ESCALATION_LIMIT_CHF:.0f} agent limit",
                lead="explain that refunds of this size are decided by a colleague, so the case was handed over",
                refund_amount_chf=amount,
            )
        self.note("refund", amount=f"{amount:.2f}")
        status, ref = self.tool("issue_refund", order_id=self.order.id, amount_chf=amount, method="original_payment")
        if status != "ok":
            raise RuntimeError(f"refund failed unexpectedly: {ref}")
        self.refund, self.outcome = ref, "refunded"
        intent = (
            "explain the parcel counts as lost and confirm the full refund that was issued"
            if why == "lost"
            else "confirm the refund that was issued and when the money arrives"
        )
        return self.say(
            intent,
            order_id=self.order.id,
            refund_id=ref["refund_id"],
            refund_amount_chf=ref["amount_chf"],
            method=ref["method"],
            business_days_min=policy.REFUND_DAYS_MIN,
            business_days_max=policy.REFUND_DAYS_MAX,
        )

    def _not_eligible(self, e: dict[str, Any], wants_compensation: bool) -> str:
        assert self.order is not None
        self.note("denied", reason=e["reason"])
        if e["reason"] == "already_refunded":
            if self.order.id not in self.seen_orders:
                self.tool("get_order", order_id=self.order.id)
                self.seen_orders.add(self.order.id)
            self.outcome = "already_refunded"
            return self.say(
                "explain that this order was already refunded in full earlier, so no further refund is possible",
                order_id=self.order.id,
                refunded_chf=self.order.refunded_chf,
            )
        if e["reason"] in ("not_delivered_yet", "not_yet_overdue"):
            return self._parcel_flow()
        self.outcome = "denied"
        facts = {
            "order_id": self.order.id,
            "delivered_on": self.order.delivery_date.isoformat() if self.order.delivery_date else None,
            "days_since_delivery": e.get("days_since_delivery"),
            "refund_window_days": e["window_days"],
        }
        if wants_compensation:
            return self._voucher(lead="explain that a refund is no longer possible because the window has passed, "
                                 "and instead offer", **facts)  # fmt: skip
        return self.say("explain politely that a refund is not possible because the refund window has passed", **facts)

    def _voucher(self, lead: str, **facts: Any) -> str:
        amount = self.rng.choice((15, 20, 25, 30, 40, 50))
        status, v = self.tool("apply_voucher", customer_id=self.scenario.customer_id, amount_chf=amount)
        if status != "ok":
            raise RuntimeError(f"voucher failed unexpectedly: {v}")
        self.voucher_given, self.outcome = True, "voucher"
        return self.say(
            f"{lead} a goodwill voucher as a gesture",
            voucher_code=v["voucher_code"],
            voucher_amount_chf=v["amount_chf"],
            voucher_valid_until=v["valid_until"],
            **facts,
        )

    def _escalate(self, reason: str, lead: str | None = None, **facts: Any) -> str:
        status, t = self.tool("escalate_to_human", reason=reason)
        if status != "ok":
            raise RuntimeError(f"escalation failed unexpectedly: {t}")
        self.escalated = True
        self.outcome = self.outcome or "escalated"
        return self.say(
            (lead or "tell the customer the case was handed to a colleague")
            + "; say when they will hear back. Do not promise any outcome",
            ticket_id=t["ticket_id"],
            response_within_hours=t["expected_response_hours"],
            **facts,
        )

    def _return_flow(self) -> str:
        assert self.order is not None
        self._maybe_lookup_order(p=0.5)
        e = self._eligibility("changed_mind")
        if not e["eligible"]:
            return self._not_eligible(e, wants_compensation=False)
        self.note("return")
        status, lab = self.tool("create_return_label", order_id=self.order.id)
        if status != "ok":
            raise RuntimeError(f"return label failed unexpectedly: {lab}")
        self.outcome = "return_label"
        return self.say(
            "explain the return: send the item back with the prepaid label; the refund (return shipping deducted) "
            "is issued once the item has arrived back. Nothing has been refunded yet",
            label_url=lab["label_url"],
            label_valid_days=lab["valid_days"],
            refund_after_return_chf=e["max_amount_chf"],
            return_shipping_chf=policy.RETURN_SHIPPING_CHF,
        )

    def _parcel_flow(self) -> str:
        assert self.order is not None
        o = self.order
        if o.id not in self.seen_orders:
            self.tool("get_order", order_id=o.id)
            self.seen_orders.add(o.id)
        self.note("parcel", tracking=o.tracking_id)
        _, ship = self.tool("get_shipping_status", tracking_id=o.tracking_id)
        last = ship["events"][-1] if isinstance(ship, dict) and ship.get("events") else {}
        if o.status == "delivered":
            self.outcome = "delivered_info"
            return self.say(
                "say the tracking shows the parcel was delivered and suggest checking the mailbox or neighbours",
                tracking_id=o.tracking_id,
                delivered_on=o.delivery_date.isoformat() if o.delivery_date else None,
            )
        e = self._eligibility("not_delivered")
        if e["eligible"]:
            return self._pay_out(e["max_amount_chf"], why="lost")
        self.outcome = "in_transit"
        return self.say(
            "say the parcel is still on its way and give the latest tracking event; promise no delivery date",
            tracking_id=o.tracking_id,
            shipped_on=o.shipped_date.isoformat(),
            last_event=last.get("event"),
            last_event_date=last.get("date"),
        )

    # helpers

    def _summary(self) -> dict[str, Any]:
        facts: dict[str, Any] = {"outcome": self.outcome}
        if self.order:
            facts["order_id"] = self.order.id
        if self.refund:
            facts |= {"refund_amount_chf": self.refund["amount_chf"], "method": self.refund["method"]}
        return facts

    def _fallback_read(self, text: str) -> CustomerRead:
        m = _ORDER_ID.search(text)
        return CustomerRead(
            order_id=m.group() if m else None,
            issue="unclear",
            wants="refund",
            asks_refund_timing=False,
            pushes_back=False,
        )

    def _last_agent_text(self) -> str:
        return next(s.text or "" for s in reversed(self.spans) if s.kind == "agent_message")
