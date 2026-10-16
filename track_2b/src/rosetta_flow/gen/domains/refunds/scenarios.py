"""What simulated customers want, always consistent with the real state of the order they pick."""

from __future__ import annotations

import random

from rosetta_flow.gen.domains.base import Scenario
from rosetta_flow.gen.domains.refunds.policy import ESCALATION_LIMIT_CHF, LOST_PARCEL_DAYS, REFUND_WINDOW_DAYS
from rosetta_flow.gen.domains.refunds.world import Order, RefundsWorld
from rosetta_flow.gen.names import LANGUAGE_WEIGHTS

TONES = ("polite and brief", "friendly and chatty", "annoyed but civil", "in a hurry, very short messages")
_PROBLEMS = {
    "damaged": "it arrived damaged",
    "defective": "it does not work properly",
    "wrong_item": "you received a different product than you ordered",
}
INTENT_WEIGHTS = {
    "problem_in_window": 25,
    "problem_late": 20,
    "changed_mind": 12,
    "big_refund": 10,
    "parcel_lost": 10,
    "parcel_late": 8,
    "already_refunded": 7,
    "wants_compensation": 8,
}


def sample_scenario(world: RefundsWorld, rng: random.Random) -> Scenario:
    """Pick an intent, then an order whose real state fits it; intents without a fitting order are skipped."""
    today = world.today
    in_window = REFUND_WINDOW_DAYS
    delivered = [o for o in world.orders.values() if o.status == "delivered" and o.refunded_chf == 0]
    in_transit = [o for o in world.orders.values() if o.status == "in_transit"]
    recent = [o for o in delivered if (today - o.delivery_date).days <= in_window]
    late = [o for o in delivered if (today - o.delivery_date).days > in_window]
    pools: dict[str, list[Order]] = {
        "problem_in_window": [o for o in recent if o.amount_chf <= ESCALATION_LIMIT_CHF],
        "problem_late": late,
        "changed_mind": recent,
        "big_refund": [o for o in recent if o.amount_chf > ESCALATION_LIMIT_CHF],
        "parcel_lost": [o for o in in_transit if (today - o.shipped_date).days > LOST_PARCEL_DAYS],
        "parcel_late": [o for o in in_transit if (today - o.shipped_date).days <= LOST_PARCEL_DAYS],
        "already_refunded": [o for o in world.orders.values() if o.refunded_chf > 0],
        "wants_compensation": late,
    }
    # Language first, so the corpus follows LANGUAGE_WEIGHTS instead of whoever happens to own fitting orders.
    langs, weights = zip(*LANGUAGE_WEIGHTS.items(), strict=True)
    lang = rng.choices(langs, weights)[0]
    in_lang = {k: [o for o in v if world.customers[o.customer_id].language == lang] for k, v in pools.items()}
    if any(in_lang.values()):
        pools = in_lang
    intents = [i for i in INTENT_WEIGHTS if pools[i]]
    intent = rng.choices(intents, [INTENT_WEIGHTS[i] for i in intents])[0]
    order = rng.choice(pools[intent])
    customer = world.customers[order.customer_id]
    item = order.items[0].name
    facts = {
        "customer_number": customer.id,
        "order_id": order.id,
        "items": ", ".join(f"{i.qty}x {i.name}" for i in order.items),
        "ordered_on": order.order_date.isoformat(),
        "paid_chf": f"{order.amount_chf:.2f}",
    }
    if order.delivery_date:
        facts["delivered_on"] = order.delivery_date.isoformat()
    problem = _PROBLEMS[rng.choice(list(_PROBLEMS))]
    goal = {
        "problem_in_window": f"Your {item}: {problem}. You want your money back.",
        "problem_late": f"Your {item}: {problem}. You noticed only now. You want your money back.",
        "changed_mind": f"You no longer want the {item} (unused). You want to return it and get your money back.",
        "big_refund": f"Your {item}: {problem}. You want a full refund quickly.",
        "parcel_lost": "Your parcel has still not arrived. You want to know where it is; "
        "if it is lost, you want your money back.",
        "parcel_late": "Your parcel has not arrived yet and you want to know when it will come.",
        "already_refunded": f"Your {item}: {problem}. You want your money back.",
        "wants_compensation": f"Your {item}: {problem}. You are unhappy and want some compensation.",
    }[intent]
    return Scenario(
        scenario_id=f"{intent}:{order.id}",
        intent=intent,
        customer_id=customer.id,
        language=customer.language,
        goal=goal,
        facts=facts,
        tone=rng.choice(TONES),
    )
