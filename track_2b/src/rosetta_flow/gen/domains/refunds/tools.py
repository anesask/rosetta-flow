"""The shop backend the agent calls. Business failures raise ToolError and reach the agent as error results."""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Any

from rosetta_flow.gen.domains.base import ToolError, ToolSpec
from rosetta_flow.gen.domains.refunds.policy import (
    ESCALATION_HOURS,
    LOST_PARCEL_DAYS,
    REASONS,
    REFUND_WINDOW_DAYS,
    RETURN_LABEL_VALID_DAYS,
    RETURN_SHIPPING_CHF,
)
from rosetta_flow.gen.domains.refunds.world import Order, RefundsWorld


def _amount(value: Any) -> float:
    # float() alone accepts True, "nan" and "inf"; any of them would corrupt the world's balances.
    if isinstance(value, bool):
        raise ToolError("amount must be a number")
    amount = float(value)
    if not math.isfinite(amount) or amount <= 0:
        raise ToolError("amount must be a positive number")
    return round(amount, 2)


def _order(world: RefundsWorld, order_id: str) -> Order:
    order = world.orders.get(str(order_id).strip().upper())
    if order is None:
        raise ToolError(f"order {order_id} not found")
    return order


def get_customer(world: RefundsWorld, customer_id: str) -> dict[str, Any]:
    c = world.customers.get(str(customer_id).strip().upper())
    if c is None:
        raise ToolError(f"customer {customer_id} not found")
    order_ids = [o.id for o in world.orders.values() if o.customer_id == c.id]
    return {"customer_id": c.id, "name": c.name, "email": c.email, "language": c.language, "orders": order_ids}


def get_order(world: RefundsWorld, order_id: str) -> dict[str, Any]:
    o = _order(world, order_id)
    return {
        "order_id": o.id,
        "customer_id": o.customer_id,
        "items": [{"sku": i.sku, "name": i.name, "qty": i.qty, "unit_price_chf": i.unit_price_chf} for i in o.items],
        "amount_chf": o.amount_chf,
        "order_date": o.order_date.isoformat(),
        "status": o.status,
        "delivery_date": o.delivery_date.isoformat() if o.delivery_date else None,
        "tracking_id": o.tracking_id,
        "refunded_chf": o.refunded_chf,
    }


def get_shipping_status(world: RefundsWorld, tracking_id: str) -> dict[str, Any]:
    o = next((o for o in world.orders.values() if o.tracking_id == str(tracking_id).strip().upper()), None)
    if o is None:
        raise ToolError(f"tracking id {tracking_id} not found")
    events = [{"date": o.shipped_date.isoformat(), "event": "handed over to carrier"}]
    if o.delivery_date:
        events.append({"date": o.delivery_date.isoformat(), "event": "delivered"})
    else:
        events.append({"date": (o.shipped_date + timedelta(days=1)).isoformat(), "event": "in sorting centre"})
    return {"tracking_id": o.tracking_id, "status": o.status, "events": events}


def eligibility(world: RefundsWorld, o: Order, reason: str) -> dict[str, Any]:
    """Single source of truth for refund eligibility, shared by the tool and tests."""
    remaining = round(o.amount_chf - o.refunded_chf, 2)
    out: dict[str, Any] = {"order_id": o.id, "reason_given": reason, "window_days": REFUND_WINDOW_DAYS}
    if remaining <= 0:
        return out | {"eligible": False, "reason": "already_refunded", "max_amount_chf": 0.0}
    if reason == "not_delivered":
        if o.status == "delivered":
            return out | {"eligible": False, "reason": "parcel_delivered", "max_amount_chf": 0.0}
        lost = (world.today - o.shipped_date).days > LOST_PARCEL_DAYS
        return out | {
            "eligible": lost,
            "reason": "parcel_lost" if lost else "not_yet_overdue",
            "max_amount_chf": remaining if lost else 0.0,
        }
    if o.status != "delivered" or o.delivery_date is None:
        return out | {"eligible": False, "reason": "not_delivered_yet", "max_amount_chf": 0.0}
    days = (world.today - o.delivery_date).days
    out["days_since_delivery"] = days
    if days > REFUND_WINDOW_DAYS:
        return out | {"eligible": False, "reason": "outside_window", "max_amount_chf": 0.0}
    if reason == "changed_mind":
        remaining = round(max(0.0, remaining - RETURN_SHIPPING_CHF), 2)
    return out | {"eligible": True, "reason": "within_window", "max_amount_chf": remaining}


def check_refund_eligibility(world: RefundsWorld, order_id: str, reason: str) -> dict[str, Any]:
    if reason not in REASONS:
        raise ToolError(f"unknown reason '{reason}', expected one of {list(REASONS)}")
    return eligibility(world, _order(world, order_id), reason)


def issue_refund(world: RefundsWorld, order_id: str, amount_chf: float, method: str) -> dict[str, Any]:
    # Deliberately does not enforce eligibility: the backend trusts the agent, so policy breaks stay possible.
    o = _order(world, order_id)
    amount = _amount(amount_chf)
    if method not in ("original_payment", "store_credit"):
        raise ToolError("method must be 'original_payment' or 'store_credit'")
    if amount > round(o.amount_chf - o.refunded_chf, 2) + 1e-9:
        raise ToolError(f"amount exceeds refundable balance of CHF {o.amount_chf - o.refunded_chf:.2f}")
    o.refunded_chf = round(o.refunded_chf + amount, 2)
    refund_id = f"R-{len(world.refunds) + 1:05d}"
    world.refunds.append({"refund_id": refund_id, "order_id": o.id, "amount_chf": amount, "method": method})
    return {"refund_id": refund_id, "status": "issued", "amount_chf": amount, "method": method}


def create_return_label(world: RefundsWorld, order_id: str) -> dict[str, Any]:
    o = _order(world, order_id)
    if o.status != "delivered":
        raise ToolError("return labels are only available for delivered orders")
    return {
        "order_id": o.id,
        "label_url": f"https://returns.shop.example/{o.id.lower()}.pdf",
        "valid_days": RETURN_LABEL_VALID_DAYS,
    }


def apply_voucher(world: RefundsWorld, customer_id: str, amount_chf: float) -> dict[str, Any]:
    c = world.customers.get(str(customer_id).strip().upper())
    if c is None:
        raise ToolError(f"customer {customer_id} not found")
    amount = _amount(amount_chf)
    code = f"GOOD-{len(world.vouchers) + 1:04d}"
    world.vouchers.append({"code": code, "customer_id": c.id, "amount_chf": amount})
    return {"voucher_code": code, "amount_chf": amount, "valid_until": (world.today + timedelta(days=365)).isoformat()}


def escalate_to_human(world: RefundsWorld, reason: str) -> dict[str, Any]:
    ticket_id = f"T-{len(world.tickets) + 1:05d}"
    world.tickets.append({"ticket_id": ticket_id, "reason": reason})
    return {"ticket_id": ticket_id, "status": "queued", "expected_response_hours": ESCALATION_HOURS}


_ID = {"type": "string"}
_CHF = {"type": "number", "description": "Amount in CHF"}
TOOLS = {
    t.name: t
    for t in [
        ToolSpec(
            "get_customer",
            "Look up a customer and their order ids.",
            {"customer_id": _ID},
            ("customer_id",),
            get_customer,
        ),
        ToolSpec(
            "get_order",
            "Look up an order: items, amount, status, delivery date, refunded amount.",
            {"order_id": _ID},
            ("order_id",),
            get_order,
        ),
        ToolSpec(
            "get_shipping_status",
            "Carrier tracking events for a parcel.",
            {"tracking_id": _ID},
            ("tracking_id",),
            get_shipping_status,
        ),
        ToolSpec(
            "check_refund_eligibility",
            "Check whether an order can be refunded and the maximum amount.",
            {"order_id": _ID, "reason": {"type": "string", "enum": list(REASONS)}},
            ("order_id", "reason"),
            check_refund_eligibility,
        ),
        ToolSpec(
            "issue_refund",
            "Refund money for an order.",
            {
                "order_id": _ID,
                "amount_chf": _CHF,
                "method": {"type": "string", "enum": ["original_payment", "store_credit"]},
            },
            ("order_id", "amount_chf", "method"),
            issue_refund,
        ),
        ToolSpec(
            "create_return_label",
            "Create a prepaid return label for a delivered order.",
            {"order_id": _ID},
            ("order_id",),
            create_return_label,
        ),
        ToolSpec(
            "apply_voucher",
            "Give the customer a goodwill voucher.",
            {"customer_id": _ID, "amount_chf": _CHF},
            ("customer_id", "amount_chf"),
            apply_voucher,
        ),
        ToolSpec(
            "escalate_to_human",
            "Hand the case to a human colleague.",
            {"reason": {"type": "string"}},
            ("reason",),
            escalate_to_human,
        ),
    ]
}
