"""The plant systems the assistant calls. Each tool reads or writes exactly one system; none joins two.

Write tools trust the caller the way real line-of-business backends do (record_inspection stores the verdict it is
given, release_lot releases), so policy breaks stay possible and the checker, not the backend, finds them.
"""

from __future__ import annotations

import math
from typing import Any

from rosetta_flow.gen.domains.base import ToolError, ToolSpec
from rosetta_flow.gen.domains.manufacturing.policy import (
    DISPOSITIONS,
    INSPECTION_INTERVAL,
    WARMUP_MIN,
)
from rosetta_flow.gen.domains.manufacturing.world import (
    NCR,
    Characteristic,
    InspectionRecord,
    Lot,
    Machine,
    PlantWorld,
    WorkOrder,
)


def _key(value: Any) -> str:
    return str(value).strip().upper()


def _wo(world: PlantWorld, work_order_id: str) -> WorkOrder:
    if (wo := world.work_orders.get(_key(work_order_id))) is None:
        raise ToolError(f"work order {work_order_id} not found")
    return wo


def _lot(world: PlantWorld, lot_id: str) -> Lot:
    if (lot := world.lots.get(_key(lot_id))) is None:
        raise ToolError(f"lot {lot_id} not found")
    return lot


def _ncr(world: PlantWorld, ncr_id: str) -> NCR:
    if (ncr := world.ncrs.get(_key(ncr_id))) is None:
        raise ToolError(f"NCR {ncr_id} not found")
    return ncr


def _machine(world: PlantWorld, machine_id: str) -> Machine:
    if (m := world.machines.get(_key(machine_id))) is None:
        raise ToolError(f"machine {machine_id} not found")
    return m


def _char(world: PlantWorld, wo: WorkOrder, characteristic: str) -> Characteristic:
    rev = world.parts[wo.part_no].revision(wo.revision)
    assert rev is not None
    found = next((c for c in rev.characteristics if c.id == _key(characteristic)), None)
    if found is None:
        raise ToolError(f"characteristic {characteristic} not on drawing {wo.part_no} rev {wo.revision}")
    return found


def _unit(wo: WorkOrder, unit: Any) -> int:
    if isinstance(unit, bool) or int(unit) != float(unit) or not 1 <= int(unit) <= wo.qty_made:
        raise ToolError(f"unit must be a whole number from 1 to {wo.qty_made} (units made so far)")
    return int(unit)


def _mm(value: Any) -> float:
    if isinstance(value, bool):
        raise ToolError("value_mm must be a number")
    v = float(value)
    if not math.isfinite(v) or v <= 0:
        raise ToolError("value_mm must be a positive number")
    return v


def _task(world: PlantWorld, kind: str, **fields: Any) -> str:
    task_id = f"TK-{len(world.tasks) + 3101}"
    world.tasks.append({"task_id": task_id, "kind": kind, **fields})
    return task_id


# PDM


def get_drawing(world: PlantWorld, part_no: str, revision: str) -> dict[str, Any]:
    part = world.parts.get(_key(part_no))
    if part is None:
        raise ToolError(f"part {part_no} not found")
    rev = part.revision(_key(revision))
    if rev is None:
        raise ToolError(f"revision {revision} of {part.part_no} not found; released: {[r.rev for r in part.revisions]}")
    return {
        "system": "PDM",
        "part_no": part.part_no,
        "description": part.name,
        "material": part.material,
        "revision": rev.rev,
        "revision_status": "current" if rev is part.current else "superseded",
        "current_revision": part.current.rev,
        "released_on": rev.released_on.isoformat(),
        "change_note": rev.change_note or None,
        "characteristics": [
            {"id": c.id, "name": c.name, "nominal_mm": c.nominal_mm, "lower_mm": c.lower_mm, "upper_mm": c.upper_mm}
            for c in rev.characteristics
        ],
    }


# MES


def get_work_order(world: PlantWorld, work_order_id: str) -> dict[str, Any]:
    wo = _wo(world, work_order_id)
    return {
        "system": "MES",
        "work_order_id": wo.id,
        "part_no": wo.part_no,
        "drawing_revision": wo.revision,
        "lot_id": wo.lot_id,
        "machine_id": wo.machine_id,
        "qty_planned": wo.qty_planned,
        "qty_made": wo.qty_made,
        "status": wo.status,
    }


def get_machine_events(world: PlantWorld, machine_id: str) -> dict[str, Any]:
    m = _machine(world, machine_id)
    return {
        "system": "MES",
        "machine_id": m.id,
        "machine": m.name,
        "status": m.status,
        "current_work_order": m.current_work_order,
        "events_today": m.events,
        "tools": [
            {
                "tool_id": t.id,
                "description": t.description,
                "parts_since_change": t.parts_since_change,
                "rated_life": t.rated_life,
            }
            for t in m.tools
        ],
    }


def request_tool_change(world: PlantWorld, machine_id: str, tool_id: str) -> dict[str, Any]:
    m = _machine(world, machine_id)
    if not any(t.id == _key(tool_id) for t in m.tools):
        raise ToolError(f"tool {tool_id} is not loaded on {m.id}")
    return {
        "system": "MES",
        "task_id": _task(world, "tool_change", machine_id=m.id, tool_id=_key(tool_id)),
        "status": "open",
        "machine_id": m.id,
        "tool_id": _key(tool_id),
    }


def request_first_article_check(world: PlantWorld, machine_id: str, work_order_id: str, pieces: int) -> dict[str, Any]:
    m = _machine(world, machine_id)
    wo = _wo(world, work_order_id)
    if isinstance(pieces, bool) or float(pieces) != int(pieces) or not 1 <= int(pieces) <= 50:
        raise ToolError("pieces must be a whole number from 1 to 50")
    task_id = _task(world, "first_article_check", machine_id=m.id, work_order_id=wo.id, pieces=int(pieces))
    return {
        "system": "QMS",
        "task_id": task_id,
        "status": "open",
        "machine_id": m.id,
        "work_order_id": wo.id,
        "pieces": int(pieces),
        "warmup_min": WARMUP_MIN,
    }


# ERP


def get_lot(world: PlantWorld, lot_id: str) -> dict[str, Any]:
    lot = _lot(world, lot_id)
    return {
        "system": "ERP",
        "lot_id": lot.id,
        "work_order_id": lot.work_order_id,
        "part_no": lot.part_no,
        "qty": lot.qty,
        "customer": lot.customer,
        "due_date": lot.due_date.isoformat(),
        "status": lot.status,
        "ncr_id": lot.ncr_id,
    }


def place_hold(world: PlantWorld, lot_id: str, ncr_id: str) -> dict[str, Any]:
    lot = _lot(world, lot_id)
    ncr = _ncr(world, ncr_id)
    if lot.status in ("shipped",):
        raise ToolError(f"lot {lot.id} already shipped; hold not possible")
    lot.status, lot.ncr_id = "on_hold", ncr.id
    return {"system": "ERP", "lot_id": lot.id, "status": "on_hold", "ncr_id": ncr.id}


def release_lot(world: PlantWorld, lot_id: str) -> dict[str, Any]:
    lot = _lot(world, lot_id)
    if lot.status != "on_hold":
        raise ToolError(f"lot {lot.id} is not on hold (status {lot.status})")
    lot.status = "released"
    return {"system": "ERP", "lot_id": lot.id, "status": "released"}


# QMS


def get_inspection_records(world: PlantWorld, work_order_id: str, characteristic: str) -> dict[str, Any]:
    wo = _wo(world, work_order_id)
    c = _char(world, wo, characteristic)
    recs = world.records_for(wo.id, c.id)
    return {
        "system": "QMS",
        "work_order_id": wo.id,
        "characteristic": c.id,
        "inspection_interval_units": INSPECTION_INTERVAL,
        "records": [
            {
                "record_id": r.id,
                "unit": r.unit,
                "value_mm": r.value_mm,
                "gauge_id": r.gauge_id,
                "date": r.on.isoformat(),
                "result": r.result,
            }
            for r in recs[-5:]
        ],
        "last_pass_unit": world.last_pass_unit(wo.id, c.id),
    }


def record_inspection(
    world: PlantWorld, work_order_id: str, characteristic: str, unit: int, value_mm: float, gauge_id: str, result: str
) -> dict[str, Any]:
    wo = _wo(world, work_order_id)
    c = _char(world, wo, characteristic)
    if result not in ("pass", "fail"):
        raise ToolError("result must be 'pass' or 'fail'")
    if _key(gauge_id) not in world.gauges:
        raise ToolError(f"gauge {gauge_id} not found")
    rec = InspectionRecord(
        f"IR-{len(world.records) + 10001}",
        wo.id,
        c.id,
        _unit(wo, unit),
        round(_mm(value_mm), c.digits),
        _key(gauge_id),
        world.today,
        result,
    )
    world.records.append(rec)
    return {"system": "QMS", "record_id": rec.id, "status": "recorded", "unit": rec.unit, "result": result}


def create_ncr(
    world: PlantWorld,
    lot_id: str,
    characteristic: str,
    measured_mm: float,
    gauge_id: str,
    scope_from_unit: int,
    scope_to_unit: int,
) -> dict[str, Any]:
    lot = _lot(world, lot_id)
    wo = world.work_orders[lot.work_order_id]
    c = _char(world, wo, characteristic)
    first, last = _unit(wo, scope_from_unit), _unit(wo, scope_to_unit)
    if first > last:
        raise ToolError("scope_from_unit must not be after scope_to_unit")
    _mm(measured_mm)
    ncr = NCR(f"NCR-{1040 + len(world.ncrs)}", lot.id, c.id, first, last, "open", None)
    world.ncrs[ncr.id] = ncr
    return {
        "system": "QMS",
        "ncr_id": ncr.id,
        "status": "open",
        "lot_id": lot.id,
        "characteristic": c.id,
        "scope_from_unit": first,
        "scope_to_unit": last,
        "scope_units": last - first + 1,
    }


def request_disposition(world: PlantWorld, ncr_id: str) -> dict[str, Any]:
    ncr = _ncr(world, ncr_id)
    qe = min(e.id for e in world.employees.values() if e.role == "quality_engineer")
    ncr.status = "awaiting_disposition"
    return {"system": "QMS", "ncr_id": ncr.id, "status": "awaiting_disposition", "assigned_to": qe}


def get_ncr(world: PlantWorld, ncr_id: str) -> dict[str, Any]:
    ncr = _ncr(world, ncr_id)
    return {
        "system": "QMS",
        "ncr_id": ncr.id,
        "lot_id": ncr.lot_id,
        "characteristic": ncr.characteristic,
        "scope_from_unit": ncr.scope_from_unit,
        "scope_to_unit": ncr.scope_to_unit,
        "status": ncr.status,
        "disposition": ncr.disposition,
        "approved_by": ncr.approved_by,
        "approved_on": ncr.approved_on.isoformat() if ncr.approved_on else None,
        "allowed_dispositions": list(DISPOSITIONS),
    }


def request_remeasurement(
    world: PlantWorld, work_order_id: str, characteristic: str, unit: int, reason: str
) -> dict[str, Any]:
    wo = _wo(world, work_order_id)
    c = _char(world, wo, characteristic)
    task_id = _task(world, "remeasurement", work_order_id=wo.id, characteristic=c.id, unit=_unit(wo, unit))
    return {
        "system": "QMS",
        "task_id": task_id,
        "status": "open",
        "work_order_id": wo.id,
        "characteristic": c.id,
        "unit": int(unit),
        "reason": str(reason)[:200],
    }


# CalTrack


def get_gauge_status(world: PlantWorld, gauge_id: str) -> dict[str, Any]:
    g = world.gauges.get(_key(gauge_id))
    if g is None:
        raise ToolError(f"gauge {gauge_id} not found")
    out = {
        "system": "CalTrack",
        "gauge_id": g.id,
        "kind": g.kind,
        "status": g.status,
        "last_calibrated": g.last_calibrated.isoformat(),
        "calibration_due": g.cal_due.isoformat(),
    }
    return out | ({"note": g.note} if g.note else {})


_S = {"type": "string"}
_INT = {"type": "integer"}
_CHAR = {"type": "string", "description": "characteristic id from the drawing, e.g. C1"}
TOOLS = {
    t.name: t
    for t in [
        ToolSpec(
            "get_work_order",
            "MES: work order with part, drawing revision, lot, machine and quantities.",
            {"work_order_id": _S},
            ("work_order_id",),
            get_work_order,
        ),
        ToolSpec(
            "get_drawing",
            "PDM: characteristics and limits of one drawing revision of a part.",
            {"part_no": _S, "revision": _S},
            ("part_no", "revision"),
            get_drawing,
        ),
        ToolSpec(
            "get_gauge_status",
            "CalTrack: calibration status of a gauge.",
            {"gauge_id": _S},
            ("gauge_id",),
            get_gauge_status,
        ),
        ToolSpec(
            "get_inspection_records",
            "QMS: latest inspection records of one characteristic of a work order.",
            {"work_order_id": _S, "characteristic": _CHAR},
            ("work_order_id", "characteristic"),
            get_inspection_records,
        ),
        ToolSpec(
            "record_inspection",
            "QMS: record a measurement with its pass/fail result.",
            {
                "work_order_id": _S,
                "characteristic": _CHAR,
                "unit": _INT,
                "value_mm": {"type": "number"},
                "gauge_id": _S,
                "result": {"type": "string", "enum": ["pass", "fail"]},
            },
            ("work_order_id", "characteristic", "unit", "value_mm", "gauge_id", "result"),
            record_inspection,
        ),
        ToolSpec(
            "create_ncr",
            "QMS: open a non-conformance report for a lot.",
            {
                "lot_id": _S,
                "characteristic": _CHAR,
                "measured_mm": {"type": "number"},
                "gauge_id": _S,
                "scope_from_unit": _INT,
                "scope_to_unit": _INT,
            },
            ("lot_id", "characteristic", "measured_mm", "gauge_id", "scope_from_unit", "scope_to_unit"),
            create_ncr,
        ),
        ToolSpec(
            "place_hold",
            "ERP: put a lot on hold under an NCR.",
            {"lot_id": _S, "ncr_id": _S},
            ("lot_id", "ncr_id"),
            place_hold,
        ),
        ToolSpec(
            "request_disposition",
            "QMS: ask the quality engineer to decide the disposition of an NCR.",
            {"ncr_id": _S},
            ("ncr_id",),
            request_disposition,
        ),
        ToolSpec("get_ncr", "QMS: NCR status, disposition and approval.", {"ncr_id": _S}, ("ncr_id",), get_ncr),
        ToolSpec(
            "get_lot", "ERP: lot quantity, customer, due date, status and NCR.", {"lot_id": _S}, ("lot_id",), get_lot
        ),
        ToolSpec("release_lot", "ERP: release a held lot for shipping.", {"lot_id": _S}, ("lot_id",), release_lot),
        ToolSpec(
            "get_machine_events",
            "MES: today's machine events, current work order and tool life.",
            {"machine_id": _S},
            ("machine_id",),
            get_machine_events,
        ),
        ToolSpec(
            "request_tool_change",
            "MES: ask for a tool change on a machine.",
            {"machine_id": _S, "tool_id": _S},
            ("machine_id", "tool_id"),
            request_tool_change,
        ),
        ToolSpec(
            "request_first_article_check",
            "QMS: ask an inspector to check the first parts after a restart.",
            {"machine_id": _S, "work_order_id": _S, "pieces": _INT},
            ("machine_id", "work_order_id", "pieces"),
            request_first_article_check,
        ),
        ToolSpec(
            "request_remeasurement",
            "QMS: ask for a measurement to be repeated with another gauge.",
            {"work_order_id": _S, "characteristic": _CHAR, "unit": _INT, "reason": _S},
            ("work_order_id", "characteristic", "unit", "reason"),
            request_remeasurement,
        ),
    ]
}
