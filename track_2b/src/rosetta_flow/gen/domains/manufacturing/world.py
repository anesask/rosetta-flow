"""Seeded fictional plant: parts with drawing revisions, work orders, lots, machines, gauges, inspections and NCRs.

The five systems are kept apart on purpose (PDM, MES, ERP, QMS, CalTrack): no record joins two of them, so the
agent has to connect them itself, which is exactly where real assistants go wrong.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from rosetta_flow.gen.domains.manufacturing.policy import (
    FIRST_PIECES_AFTER_STOP,
    INSPECTION_INTERVAL,
    SPINDLE_STOP_MIN,
    TODAY,
)
from rosetta_flow.gen.names import LANGUAGE_WEIGHTS, NAMES
from rosetta_flow.trace import Language


@dataclass(frozen=True)
class Characteristic:
    id: str
    name: str
    nominal_mm: float
    tol_plus_mm: float
    tol_minus_mm: float  # magnitude below nominal
    digits: int
    gauge_kind: str

    @property
    def lower_mm(self) -> float:
        return round(self.nominal_mm - self.tol_minus_mm, self.digits)

    @property
    def upper_mm(self) -> float:
        return round(self.nominal_mm + self.tol_plus_mm, self.digits)

    def within(self, value: float) -> bool:
        return self.lower_mm - 1e-9 <= value <= self.upper_mm + 1e-9


def plausible_reading(value: float, char: dict[str, Any]) -> bool:
    """Whether a measured value can belong to this drawing characteristic: within ten tolerance bands of nominal.
    A share of the nominal was too wide (32.0 mm "fitted" both a 32 mm spacing and a 40 mm width); real
    out-of-tolerance readings miss the band by a few hundredths, far inside ten bands."""
    band = max(char["upper_mm"] - char["lower_mm"], 0.001)
    return abs(value - char["nominal_mm"]) <= 10 * band


@dataclass(frozen=True)
class Revision:
    rev: str
    released_on: date
    characteristics: tuple[Characteristic, ...]
    change_note: str

    def char(self, char_id: str) -> Characteristic:
        return next(c for c in self.characteristics if c.id == char_id)


@dataclass
class Part:
    part_no: str
    name: str
    names: dict[Language, str]
    material: str
    revisions: list[Revision]  # oldest first, last one is current

    def revision(self, rev: str) -> Revision | None:
        return next((r for r in self.revisions if r.rev == rev), None)

    @property
    def current(self) -> Revision:
        return self.revisions[-1]


@dataclass
class Employee:
    id: str
    name: str
    role: str  # operator | inspector | supervisor | quality_engineer
    language: Language


@dataclass
class Gauge:
    id: str
    kind: str
    status: str  # valid | expired | blocked
    last_calibrated: date
    cal_due: date
    note: str = ""


@dataclass
class Tool:
    id: str
    description: str
    rated_life: int
    parts_since_change: int

    @property
    def worn(self) -> bool:
        return self.parts_since_change >= self.rated_life


@dataclass
class Machine:
    id: str
    name: str
    tools: list[Tool]
    events: list[dict[str, Any]]
    status: str  # running | stopped
    current_work_order: str | None = None

    @property
    def last_stop_min(self) -> int | None:
        """Duration of the latest spindle stop that no first-article check has cleared yet."""
        for e in reversed(self.events):
            if e["event"] == "first_article_check" and e.get("result") == "passed":
                return None
            if e["event"] == "spindle_stop":
                return e["duration_min"]
        return None


@dataclass
class WorkOrder:
    id: str
    part_no: str
    revision: str
    lot_id: str
    machine_id: str
    qty_planned: int
    qty_made: int
    status: str  # in_production | completed


@dataclass
class InspectionRecord:
    id: str
    work_order_id: str
    characteristic: str
    unit: int
    value_mm: float
    gauge_id: str
    on: date
    result: str  # pass | fail


@dataclass
class Lot:
    id: str
    work_order_id: str
    part_no: str
    qty: int
    customer: str
    due_date: date
    status: str  # in_production | on_hold | released | shipped
    ncr_id: str | None = None


@dataclass
class NCR:
    id: str
    lot_id: str
    characteristic: str
    scope_from_unit: int
    scope_to_unit: int
    # open -> awaiting_disposition (QE asked) -> awaiting_approval (proposal made) -> approved
    status: str
    disposition: str | None  # proposed or approved disposition
    approved_by: str | None = None
    approved_on: date | None = None


@dataclass
class PlantWorld:
    seed: int
    today: date
    parts: dict[str, Part]
    employees: dict[str, Employee]
    gauges: dict[str, Gauge]
    machines: dict[str, Machine]
    work_orders: dict[str, WorkOrder]
    lots: dict[str, Lot]
    records: list[InspectionRecord]
    ncrs: dict[str, NCR]
    tasks: list[dict[str, Any]] = field(default_factory=list)

    def records_for(self, wo_id: str, char_id: str) -> list[InspectionRecord]:
        return sorted(
            (r for r in self.records if r.work_order_id == wo_id and r.characteristic == char_id), key=lambda r: r.unit
        )

    def last_pass_unit(self, wo_id: str, char_id: str) -> int:
        passed = [r.unit for r in self.records_for(wo_id, char_id) if r.result == "pass"]
        return max(passed, default=0)


ID, OD, LEN = "bore gauge", "outside micrometer", "caliper"
# (part_no, names, material, [(char id, name, nominal, +tol, -tol, digits, gauge kind)])
CATALOGUE: list[tuple[str, dict[Language, str], str, list[tuple[str, str, float, float, float, int, str]]]] = [
    ("PN-4471", {"de": "Ventilgehäuse", "fr": "corps de vanne", "it": "corpo valvola", "en": "valve housing"},
     "EN AW-6082", [("C1", "bore diameter", 12.000, 0.018, 0.0, 3, ID),
                    ("C2", "overall length", 45.00, 0.05, 0.05, 2, LEN),
                    ("C3", "flange thickness", 6.00, 0.03, 0.03, 2, LEN)]),
    ("PN-3820", {"de": "Aktuatorwelle", "fr": "arbre d'actionneur", "it": "albero attuatore", "en": "actuator shaft"},
     "1.4404", [("C1", "bearing seat diameter", 8.000, 0.0, 0.009, 3, OD),
                ("C2", "shaft length", 120.00, 0.10, 0.10, 2, LEN),
                ("C3", "groove width", 1.10, 0.05, 0.0, 2, LEN)]),
    ("PN-5102", {"de": "Kolben", "fr": "piston", "it": "pistone", "en": "piston"},
     "1.7225", [("C1", "outer diameter", 24.980, 0.010, 0.010, 3, OD),
                ("C2", "ring groove depth", 1.60, 0.02, 0.02, 2, LEN),
                ("C3", "piston height", 18.00, 0.05, 0.05, 2, LEN)]),
    ("PN-2275", {"de": "Verteilerblock", "fr": "bloc distributeur", "it": "blocco distributore",
                 "en": "manifold block"},
     "EN AW-7075", [("C1", "port bore diameter", 6.000, 0.012, 0.0, 3, ID),
                    ("C2", "hole spacing", 32.00, 0.02, 0.02, 2, LEN),
                    ("C3", "block width", 40.00, 0.05, 0.05, 2, LEN)]),
    ("PN-6630", {"de": "Lagerbuchse", "fr": "douille de palier", "it": "boccola", "en": "bearing bushing"},
     "CuSn8", [("C1", "inner diameter", 10.000, 0.015, 0.0, 3, ID),
               ("C2", "outer diameter", 14.000, 0.0, 0.011, 3, OD),
               ("C3", "bushing length", 20.00, 0.05, 0.05, 2, LEN)]),
    ("PN-1958", {"de": "Anschlussflansch", "fr": "bride de raccordement", "it": "flangia di raccordo",
                 "en": "connection flange"},
     "1.4301", [("C1", "centre bore diameter", 30.000, 0.021, 0.0, 3, ID),
                ("C2", "bolt circle diameter", 52.00, 0.03, 0.03, 2, LEN),
                ("C3", "flange thickness", 8.00, 0.05, 0.05, 2, LEN)]),
]  # fmt: skip

MACHINES = [
    ("MC-01", "5-axis machining centre", "milling"),
    ("MC-02", "5-axis machining centre", "milling"),
    ("MC-03", "mill-turn centre", "mill_turn"),
    ("MC-04", "mill-turn centre", "mill_turn"),
    ("MC-05", "CNC lathe", "turning"),
    ("MC-06", "CNC lathe", "turning"),
    ("MC-07", "horizontal machining centre", "milling"),
    ("MC-08", "honing machine", "honing"),
]
# Tools a machine of each kind actually carries, with rated life in parts.
TOOL_TYPES = {
    "milling": [("end mill Ø10", 900), ("face mill Ø50", 1500), ("drill Ø5.8", 1200), ("boring bar Ø11.8", 600),
                ("reamer Ø12 H7", 800)],
    "mill_turn": [("turning insert CNMG", 400), ("grooving insert 1.1", 500), ("end mill Ø10", 900),
                  ("drill Ø5.8", 1200), ("boring bar Ø11.8", 600)],
    "turning": [("turning insert CNMG", 400), ("finishing insert VBMT", 350), ("grooving insert 1.1", 500),
                ("boring bar Ø11.8", 600)],
    "honing": [("honing stone coarse", 300), ("honing stone fine", 450), ("plateau brush", 600)],
}  # fmt: skip
STOP_REASONS = ["chip jam", "coolant pump fault", "power dip", "tool breakage alarm", "door interlock fault",
                "material shortage", "shift handover", "spindle overload alarm"]  # fmt: skip
STOP_MINUTES = [8, 12, 18, 25, 35, 45, 60, 90]  # half below, half at or over SPINDLE_STOP_MIN
CUSTOMERS = ["Alvara Aktorik AG", "Hydrovex SA", "Valtrona SA", "Fluxmere Ltd"]
ROLES = {"operator": ("OP", 2), "inspector": ("QI", 1), "supervisor": ("SV", 1)}
NCR_STATES = [  # status, disposition, approved
    ("awaiting_approval", "use_as_is", False),
    ("awaiting_approval", "rework", False),
    ("approved", "use_as_is", True),
    ("approved", "use_as_is", True),
    ("approved", "scrap", True),
    ("approved", "rework", True),
]

assert sum(m >= SPINDLE_STOP_MIN for m in STOP_MINUTES) == len(STOP_MINUTES) // 2


def make_world(seed: int) -> PlantWorld:
    rng = random.Random(seed)
    parts = {p.part_no: p for p in (_part(rng, *spec) for spec in CATALOGUE)}
    employees = _employees(rng)
    gauges = _gauges(rng)
    machines = _machines(rng)
    work_orders: dict[str, WorkOrder] = {}
    lots: dict[str, Lot] = {}
    records: list[InspectionRecord] = []
    ncrs: dict[str, NCR] = {}
    valid = {k: [g for g in gauges.values() if g.kind == k and g.status == "valid"] for k in (ID, OD, LEN)}

    machine_ids = list(machines)
    states = list(NCR_STATES)
    rng.shuffle(states)
    completed_status = ["on_hold"] * len(states) + ["released"] * 3 + ["shipped"] * 3
    for i in range(len(machine_ids) + len(completed_status)):
        running = i < len(machine_ids)
        part = rng.choice(list(parts.values()))
        # Work orders released before the latest engineering change keep their older revision (a third of them).
        rev = part.revisions[-2].rev if len(part.revisions) > 1 and rng.random() < 0.35 else part.current.rev
        wo_id = _unique(rng, work_orders, "WO-", 5)
        lot_id = _unique(rng, lots, "L-", 4)
        qty_planned = rng.randrange(120, 420, INSPECTION_INTERVAL)
        if running:
            qty_made = rng.randrange(3 * INSPECTION_INTERVAL, qty_planned, INSPECTION_INTERVAL)
            machine_id = machine_ids[i]
            machines[machine_id].current_work_order = wo_id
        else:
            qty_made = qty_planned
            machine_id = rng.choice(machine_ids)
        wo = WorkOrder(
            wo_id,
            part.part_no,
            rev,
            lot_id,
            machine_id,
            qty_planned,
            qty_made,
            "in_production" if running else "completed",
        )
        work_orders[wo_id] = wo
        revision = part.revision(rev)
        assert revision is not None
        # Running orders: the newest unit is the one being measured now, so its record does not exist yet.
        last_recorded = qty_made - INSPECTION_INTERVAL if running else qty_made
        for c in revision.characteristics:
            skipped = rng.random() < 0.3 and running  # a missed inspection widens the NCR scope
            for unit in range(INSPECTION_INTERVAL, last_recorded + 1, INSPECTION_INTERVAL):
                if skipped and unit == last_recorded:
                    continue
                records.append(
                    InspectionRecord(
                        f"IR-{len(records) + 10001}",
                        wo_id,
                        c.id,
                        unit,
                        _good_value(rng, c),
                        rng.choice(valid[c.gauge_kind]).id,
                        TODAY - timedelta(days=(last_recorded - unit) // 60),
                        "pass",
                    )
                )
        lot = Lot(
            lot_id,
            wo_id,
            part.part_no,
            qty_planned,
            rng.choice(CUSTOMERS),
            TODAY + timedelta(days=rng.randint(0 if not running else 3, 21)),
            "in_production" if running else completed_status[i - len(machine_ids)],
        )
        lots[lot_id] = lot
        if lot.status == "on_hold":
            status, disposition, approved = states.pop()
            c = rng.choice(revision.characteristics)
            ncr_id = f"NCR-{1040 + len(ncrs)}"
            first = rng.randrange(INSPECTION_INTERVAL, qty_made - INSPECTION_INTERVAL, INSPECTION_INTERVAL) + 1
            qe = rng.choice([e for e in employees.values() if e.role == "quality_engineer"])
            ncrs[ncr_id] = NCR(
                ncr_id,
                lot_id,
                c.id,
                first,
                first + INSPECTION_INTERVAL - 1,
                status,
                disposition,
                qe.id if approved else None,
                TODAY - timedelta(days=rng.randint(0, 3)) if approved else None,
            )
            lot.ncr_id = ncr_id
    return PlantWorld(seed, TODAY, parts, employees, gauges, machines, work_orders, lots, records, ncrs)


def _part(rng: random.Random, part_no: str, names: dict[Language, str], material: str, chars: list) -> Part:
    current = tuple(Characteristic(*c) for c in chars)
    revisions = [Revision("C", TODAY - timedelta(days=rng.randint(20, 120)), current, "")]
    # Older revisions were looser on one characteristic: engineering tightened it later (the usual direction).
    for _ in range(rng.choice((0, 1, 1, 2))):
        newer = revisions[0]
        i = rng.randrange(len(newer.characteristics))
        c = newer.characteristics[i]
        looser = (
            Characteristic(
                c.id, c.name, c.nominal_mm, round(c.tol_plus_mm * 1.5, c.digits), c.tol_minus_mm, c.digits, c.gauge_kind
            )
            if c.tol_plus_mm
            else Characteristic(
                c.id, c.name, c.nominal_mm, c.tol_plus_mm, round(c.tol_minus_mm * 1.5, c.digits), c.digits, c.gauge_kind
            )
        )
        older = Revision(
            "?",
            newer.released_on - timedelta(days=rng.randint(90, 400)),
            (*newer.characteristics[:i], looser, *newer.characteristics[i + 1 :]),
            "",
        )
        revisions[0] = Revision(
            newer.rev, newer.released_on, newer.characteristics, f"{c.id} {c.name}: tolerance tightened"
        )
        revisions.insert(0, older)
    # Letters follow the release order: the current revision is the highest letter.
    letters = "ABC"[3 - len(revisions) :]
    revisions = [
        Revision(letter, r.released_on, r.characteristics, r.change_note)
        for letter, r in zip(letters, revisions, strict=True)
    ]
    return Part(part_no, names["en"], names, material, revisions)


def _good_value(rng: random.Random, c: Characteristic) -> float:
    centre = (c.lower_mm + c.upper_mm) / 2
    half = (c.upper_mm - c.lower_mm) / 2
    return round(centre + rng.uniform(-0.6, 0.6) * half, c.digits)


def _employees(rng: random.Random) -> dict[str, Employee]:
    out: dict[str, Employee] = {}
    counters = {"OP": 11, "QI": 1, "SV": 1}
    for lang in LANGUAGE_WEIGHTS:
        for role, (prefix, n) in ROLES.items():
            for _ in range(n):
                eid = f"{prefix}-{counters[prefix]:02d}"
                counters[prefix] += 1
                out[eid] = Employee(eid, _name(rng, lang), role, lang)
    for i in (1, 2):
        lang = rng.choice(list(LANGUAGE_WEIGHTS))
        out[f"QE-{i:02d}"] = Employee(f"QE-{i:02d}", _name(rng, lang), "quality_engineer", lang)
    return out


def _name(rng: random.Random, lang: Language) -> str:
    return f"{rng.choice(NAMES[lang][0])} {rng.choice(NAMES[lang][1])}"


def _gauges(rng: random.Random) -> dict[str, Gauge]:
    out: dict[str, Gauge] = {}
    for kind in (ID, OD, LEN):
        for status in ("valid", "valid", "valid", "expired", "blocked"):
            gid = _unique(rng, out, "MM-0", 3)
            if status == "expired":
                due = TODAY - timedelta(days=rng.randint(2, 40))
            else:
                due = TODAY + timedelta(days=rng.randint(10, 300))
            note = "damaged anvil, withdrawn from use" if status == "blocked" else ""
            out[gid] = Gauge(gid, kind, status, due - timedelta(days=365), due, note)
    return out


def _machines(rng: random.Random) -> dict[str, Machine]:
    stops = list(STOP_MINUTES)
    rng.shuffle(stops)
    tool_ids = iter(range(101, 200))
    out = {}
    worn_on = set(rng.sample(range(len(MACHINES)), k=3))
    for i, (mid, name, kind) in enumerate(MACHINES):
        tools = []
        for desc, life in rng.sample(TOOL_TYPES[kind], k=3):
            tools.append(Tool(f"T-{next(tool_ids)}", desc, life, rng.randint(life // 10, int(life * 0.85))))
        if i in worn_on:
            t = rng.choice(tools)
            t.parts_since_change = t.rated_life
        out[mid] = Machine(mid, name, tools, _events(rng, tools, stops[i]), "stopped")
    return out


def _events(rng: random.Random, tools: list[Tool], stop_min: int) -> list[dict[str, Any]]:
    minute = 6 * 60
    events: list[dict[str, Any]] = [{"time": _hhmm(minute), "event": "shift_start"}]
    if rng.random() < 0.3:  # an earlier long stop, already cleared by a passed first-article check
        minute += rng.randint(30, 90)
        events.append(
            {"time": _hhmm(minute), "event": "spindle_stop", "duration_min": 50, "reason": rng.choice(STOP_REASONS)}
        )
        minute += 50 + 25
        events.append(
            {
                "time": _hhmm(minute),
                "event": "first_article_check",
                "pieces": FIRST_PIECES_AFTER_STOP,
                "result": "passed",
            }
        )
    if rng.random() < 0.5:
        minute += rng.randint(20, 80)
        events.append({"time": _hhmm(minute), "event": "tool_change", "tool_id": rng.choice(tools).id})
    minute += rng.randint(30, 120)
    events.append(
        {"time": _hhmm(minute), "event": "spindle_stop", "duration_min": stop_min, "reason": rng.choice(STOP_REASONS)}
    )
    return events


def _hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _unique(rng: random.Random, taken: dict[str, Any], prefix: str, digits: int) -> str:
    while (key := f"{prefix}{rng.randrange(10 ** (digits - 1), 10**digits)}") in taken:
        pass
    return key
