"""What simulated plant staff ask, always consistent with the real state of the plant they ask about."""

from __future__ import annotations

import random

from rosetta_flow.gen.domains.base import Scenario
from rosetta_flow.gen.domains.manufacturing.policy import SPINDLE_STOP_MIN
from rosetta_flow.gen.domains.manufacturing.world import Characteristic, Employee, PlantWorld
from rosetta_flow.gen.names import LANGUAGE_WEIGHTS

TONES = ("short and factual", "friendly, a bit chatty", "stressed, the line is waiting", "careful and precise")
INTENT_WEIGHTS = {
    "measurement_ok": 18,
    "measurement_out": 16,
    "gauge_invalid": 10,
    "release_approved": 10,
    "release_pending": 9,
    "release_blocked": 6,
    "restart_long_stop": 12,
    "restart_short_stop": 7,
    "tool_worn": 12,
}
FAMILY = {
    "measurement_ok": "measurement",
    "measurement_out": "measurement",
    "gauge_invalid": "measurement",
    "release_approved": "release",
    "release_pending": "release",
    "release_blocked": "release",
    "restart_long_stop": "restart",
    "restart_short_stop": "restart",
    "tool_worn": "restart",
}
_ROLE_FOR = {"measurement": ("operator", "inspector"), "release": ("supervisor",), "restart": ("operator",)}


def sample_scenario(world: PlantWorld, rng: random.Random) -> Scenario:
    langs, weights = zip(*LANGUAGE_WEIGHTS.items(), strict=True)
    lang = rng.choices(langs, weights)[0]
    pools = _pools(world)
    intents = [i for i in INTENT_WEIGHTS if pools[i]]
    intent = rng.choices(intents, [INTENT_WEIGHTS[i] for i in intents])[0]
    family = FAMILY[intent]
    people = [e for e in world.employees.values() if e.language == lang and e.role in _ROLE_FOR[family]]
    who = rng.choice(people)
    target = rng.choice(pools[intent])
    if family == "measurement":
        facts, goal = _measurement(world, rng, intent, target, who)
    elif family == "release":
        lot = world.lots[target]
        facts = {"lot_id": lot.id, "customer": lot.customer, "due_date": lot.due_date.isoformat()}
        goal = (
            f"You are {who.name}, production supervisor. Lot {lot.id} for {lot.customer} is due on "
            f"{lot.due_date.isoformat()}. You want it released for shipping today if at all possible."
        )
    else:
        m = world.machines[target]
        stop = next(e for e in reversed(m.events) if e["event"] == "spindle_stop")
        facts = {
            "machine_id": m.id,
            "work_order_id": m.current_work_order or "",
            "stop_minutes": str(stop["duration_min"]),
            "stop_reason": stop["reason"],
        }
        goal = (
            f"You are {who.name}, machine operator. Your machine {m.id} stopped today for about "
            f"{stop['duration_min']} minutes ({stop['reason']}). The cause is fixed and you want to restart "
            f"production on work order {m.current_work_order} now."
        )
    return Scenario(f"{intent}:{target}", intent, who.id, who.language, goal, facts, rng.choice(TONES))


def _pools(world: PlantWorld) -> dict[str, list[str]]:
    running = [wo.id for wo in world.work_orders.values() if wo.status == "in_production"]
    held = [(lot.id, world.ncrs[lot.ncr_id]) for lot in world.lots.values() if lot.status == "on_hold" and lot.ncr_id]
    machines = list(world.machines.values())

    def long_stop(m) -> bool:
        return (m.last_stop_min or 0) >= SPINDLE_STOP_MIN

    return {
        "measurement_ok": running,
        "measurement_out": running,
        "gauge_invalid": running,
        "release_approved": [lid for lid, n in held if n.status == "approved" and n.disposition == "use_as_is"],
        "release_pending": [lid for lid, n in held if n.status != "approved"],
        "release_blocked": [lid for lid, n in held if n.status == "approved" and n.disposition != "use_as_is"],
        "restart_long_stop": [m.id for m in machines if long_stop(m) and m.current_work_order],
        "restart_short_stop": [
            m.id for m in machines if not long_stop(m) and not any(t.worn for t in m.tools) and m.current_work_order
        ],
        "tool_worn": [
            m.id for m in machines if not long_stop(m) and any(t.worn for t in m.tools) and m.current_work_order
        ],
    }


def _measurement(
    world: PlantWorld, rng: random.Random, intent: str, wo_id: str, who: Employee
) -> tuple[dict[str, str], str]:
    wo = world.work_orders[wo_id]
    part = world.parts[wo.part_no]
    revision = part.revision(wo.revision)
    assert revision is not None
    c = rng.choice(revision.characteristics)
    current = part.current.char(c.id)
    if intent == "gauge_invalid":
        gauges = [g for g in world.gauges.values() if g.kind == c.gauge_kind and g.status != "valid"]
        value = _inside(rng, c) if rng.random() < 0.5 else _outside(rng, c)
    else:
        gauges = [g for g in world.gauges.values() if g.kind == c.gauge_kind and g.status == "valid"]
        if intent == "measurement_ok":
            # Revision trap: inside the work order's (older, looser) limits but outside the current drawing.
            value = _between(rng, c, current) if current != c and rng.random() < 0.6 else _inside(rng, c)
        else:
            value = _outside(rng, c)
    gauge = rng.choice(gauges)
    unit = wo.qty_made
    text = f"{value:.{c.digits}f}"
    role = "inspector" if who.role == "inspector" else "machine operator"
    facts = {
        "work_order_id": wo.id,
        "machine_id": wo.machine_id,
        "characteristic": c.name,
        "measured_mm": text,
        "gauge_id": gauge.id,
        "unit_number": str(unit),
    }
    goal = (
        f"You are {who.name}, {role}. You just measured the {c.name} of unit {unit} of work order {wo.id} with "
        f"gauge {gauge.id}: {text} mm. You want to know whether the part is OK and what happens next."
    )
    return facts, goal


def _inside(rng: random.Random, c: Characteristic) -> float:
    step = 10**-c.digits
    return round(rng.uniform(c.lower_mm + step, c.upper_mm - step), c.digits)


def _outside(rng: random.Random, c: Characteristic) -> float:
    step = 10**-c.digits
    over = rng.randint(1, 6) * step
    if c.tol_plus_mm and (not c.tol_minus_mm or rng.random() < 0.6):
        return round(c.upper_mm + over, c.digits)
    return round(c.lower_mm - over, c.digits)


def _between(rng: random.Random, older: Characteristic, current: Characteristic) -> float:
    """A value inside the older limits but outside the current, tighter ones."""
    step = 10**-older.digits
    if older.upper_mm > current.upper_mm:
        return round(rng.uniform(current.upper_mm + step, older.upper_mm), older.digits)
    return round(rng.uniform(older.lower_mm, current.lower_mm - step), older.digits)
