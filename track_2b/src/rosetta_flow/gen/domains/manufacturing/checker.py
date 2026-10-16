"""Policy checker over finished plant traces. Q1 to Q6 are exact (tool calls and results); release wording in
messages (Q4), language (Q7) and prices (Q8) are keyword heuristics and never certain."""

from __future__ import annotations

import math
import re
from typing import Any

from rosetta_flow.gen.domains.base import Violation, tool_exchanges
from rosetta_flow.gen.domains.manufacturing.policy import FIRST_PIECES_AFTER_STOP, SPINDLE_STOP_MIN
from rosetta_flow.gen.domains.manufacturing.world import PlantWorld, plausible_reading
from rosetta_flow.gen.lang import guess_language
from rosetta_flow.trace import ErrorType, Span, SpanKind, Trace

E = ErrorType
_RELEASED = re.compile(r"\b(freigegeben|libér[ée]e?s?|rilasciat[oaie]|svincolat[oaie]|released)\b", re.IGNORECASE)
_APPROVED = re.compile(r"\b(genehmigt|approved|approuv[ée]e?s?|approvat[oaie])\b", re.IGNORECASE)
_NEGATION = re.compile(
    r"\b(nicht|noch|kein\w*|erst|pas|aucun\w*|encore|non|ancora|not|cannot|can't|yet|until|once|sobald|dès que|"
    r"une fois|appena|"
    r"wird|werden|sera|seront|verrà|verranno|will|must|muss|doit|deve|needs?)\b",
    re.IGNORECASE,
)
_PRICE = re.compile(r"\b(CHF|Fr\.)\s?\d", re.IGNORECASE)


def check(trace: Trace, world: PlantWorld) -> list[Violation]:
    out: list[Violation] = []
    gauge_seen: dict[str, tuple[str, dict[str, Any]]] = {}  # gauge id -> (result span, result)
    wo_seen: dict[str, tuple[str, dict[str, Any]]] = {}
    drawings: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
    records_seen: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
    ncr_seen: dict[str, tuple[str, dict[str, Any]]] = {}
    events: list[tuple[str, dict[str, Any]]] = []
    fails: list[Span] = []
    calls = {
        name: []
        for name in (
            "create_ncr",
            "place_hold",
            "request_disposition",
            "request_tool_change",
            "request_first_article_check",
        )
    }
    release_ok_at: str | None = None

    for call, result in tool_exchanges(trace):
        args = call.args or {}
        ok = result is not None and result.status == "ok"
        res = result.result if ok and isinstance(result.result, dict) else {}
        if call.tool in calls and ok:
            calls[call.tool].append(call)
        match call.tool:
            case "get_gauge_status" if ok:
                gauge_seen[res["gauge_id"]] = (result.id, res)
            case "get_work_order" if ok:
                wo_seen[res["work_order_id"]] = (result.id, res)
            case "get_drawing" if ok:
                drawings[(res["part_no"], res["revision"])] = (result.id, res)
                for wo_span, wo in wo_seen.values():
                    if wo["part_no"] == res["part_no"] and wo["drawing_revision"] != res["revision"]:
                        detail = f"drawing rev {res['revision']} used, work order is on rev {wo['drawing_revision']}"
                        out.append(Violation("Q2", E.WRONG_TOOL_ARGS, (wo_span, call.id), detail))
            case "get_inspection_records" if ok:
                records_seen[(res["work_order_id"], res["characteristic"])] = (result.id, res)
            case "get_ncr" if ok:
                ncr_seen[res["ncr_id"]] = (result.id, res)
            case "get_machine_events" if ok:
                events.append((result.id, res))
            case "record_inspection":
                out += _check_record(call, args, gauge_seen, wo_seen, drawings)
                if ok and args.get("result") == "fail":
                    fails.append(call)
            case "create_ncr":
                out += _check_ncr(call, args, wo_seen, records_seen, gauge_seen)
            case "release_lot":
                lot = str(args.get("lot_id", "")).upper()
                seen = [v for v in ncr_seen.values() if v[1].get("lot_id") == lot]
                if not seen:
                    out.append(Violation("Q4", E.SKIPPED_REQUIRED_STEP, (call.id,), "release without reading the NCR"))
                elif not _approved_use_as_is(seen[-1][1]):
                    out.append(
                        Violation(
                            "Q4",
                            E.POLICY_VIOLATION,
                            (seen[-1][0], call.id),
                            "release although use_as_is is not approved",
                        )
                    )
                if ok and release_ok_at is None:
                    release_ok_at = result.id

    for call in fails:  # Q3: a recorded failure needs NCR, hold and disposition request after it
        for step in ("create_ncr", "place_hold", "request_disposition"):
            if not any(c.id > call.id for c in calls[step]):
                out.append(Violation("Q3", E.SKIPPED_REQUIRED_STEP, (call.id,), f"failed measurement without {step}"))
    for span_id, ev in events:  # Q5 and Q6 apply to every machine the agent looked at
        for tool in ev.get("tools", []):
            worn = tool["parts_since_change"] >= tool["rated_life"]
            if worn and not any(c.args.get("tool_id") == tool["tool_id"] for c in calls["request_tool_change"]):
                out.append(
                    Violation("Q5", E.SKIPPED_REQUIRED_STEP, (span_id,), f"worn tool {tool['tool_id']} not changed")
                )
        stop = _open_stop(ev.get("events_today", []))
        if stop is not None and stop >= SPINDLE_STOP_MIN:
            fai = [c for c in calls["request_first_article_check"] if c.args.get("machine_id") == ev["machine_id"]]
            if not fai:
                out.append(
                    Violation("Q6", E.SKIPPED_REQUIRED_STEP, (span_id,), f"{stop} min stop without first-article check")
                )
            elif any(_int(c.args.get("pieces")) < FIRST_PIECES_AFTER_STOP for c in fai):
                out.append(Violation("Q6", E.POLICY_VIOLATION, (fai[0].id,), "fewer first pieces than required"))

    for s in trace.spans:
        if s.kind is not SpanKind.AGENT_MESSAGE or not s.text:
            continue
        before_release = release_ok_at is None or s.id < release_ok_at
        approval_seen = any(r.get("status") == "approved" and sid < s.id for sid, r in ncr_seen.values())
        claims = [_RELEASED] if approval_seen else [_RELEASED, _APPROVED]
        if before_release and any(
            rx.search(x) and not _NEGATION.search(x) for x in _sentences(s.text) for rx in claims
        ):
            out.append(
                Violation(
                    "Q4",
                    E.FALSE_COMPLETION,
                    (s.id,),
                    "release or approval stated before a tool confirmed it",
                    certain=False,
                )
            )
        if _PRICE.search(s.text):
            out.append(Violation("Q8", E.DATA_LEAK, (s.id,), "price in a chat message", certain=False))
        lang = guess_language(s.text)
        if lang is not None and lang != trace.language:
            out.append(
                Violation(
                    "Q7",
                    E.LANGUAGE_MISMATCH,
                    (s.id,),
                    f"reply in {lang}, requester wrote {trace.language}",
                    certain=False,
                )
            )
    return out


def _check_record(call, args, gauge_seen, wo_seen, drawings) -> list[Violation]:
    out = []
    gauge = gauge_seen.get(str(args.get("gauge_id", "")).upper())
    if gauge is None:
        out.append(Violation("Q1", E.SKIPPED_REQUIRED_STEP, (call.id,), "measurement recorded without gauge check"))
    elif gauge[1].get("status") != "valid":
        out.append(
            Violation("Q1", E.POLICY_VIOLATION, (gauge[0], call.id), f"gauge {gauge[1]['status']}, measurement used")
        )
    wo = wo_seen.get(str(args.get("work_order_id", "")).upper())
    value = _float(args.get("value_mm"))
    if wo is None or value is None:
        return out
    drawing = drawings.get((wo[1]["part_no"], wo[1]["drawing_revision"]))
    if drawing is None:
        out.append(Violation("Q2", E.SKIPPED_REQUIRED_STEP, (call.id,), "verdict without the work order's drawing"))
        return out
    char = next(
        (c for c in drawing[1]["characteristics"] if c["id"] == str(args.get("characteristic", "")).upper()), None
    )
    if char is not None and not plausible_reading(value, char):
        out.append(
            Violation(
                "Q2", E.WRONG_TOOL_ARGS, (drawing[0], call.id), f"{value} mm cannot be {char['id']} {char['name']}"
            )
        )
    elif char is not None:
        inside = char["lower_mm"] - 1e-9 <= value <= char["upper_mm"] + 1e-9
        if (args.get("result") == "pass") != inside:
            out.append(
                Violation(
                    "Q2",
                    E.CONTRADICTS_TOOL_RESULT,
                    (drawing[0], call.id),
                    f"{value} recorded as {args.get('result')} against {char['lower_mm']}..{char['upper_mm']}",
                )
            )
    return out


def _check_ncr(call, args, wo_seen, records_seen, gauge_seen) -> list[Violation]:
    out = []
    lot = str(args.get("lot_id", "")).upper()
    wo = next((w for w in wo_seen.values() if w[1]["lot_id"] == lot), None)
    if wo is None:
        return out
    records = records_seen.get((wo[1]["work_order_id"], str(args.get("characteristic", "")).upper()))
    if records is None:
        out.append(Violation("Q3", E.SKIPPED_REQUIRED_STEP, (call.id,), "NCR scope set without inspection records"))
    elif _int(args.get("scope_from_unit")) != records[1]["last_pass_unit"] + 1:
        out.append(
            Violation(
                "Q3",
                E.POLICY_VIOLATION,
                (records[0], call.id),
                f"scope starts at {args.get('scope_from_unit')}, last pass was {records[1]['last_pass_unit']}",
            )
        )
    if str(args.get("gauge_id", "")).upper() not in gauge_seen:
        out.append(
            Violation("Q1", E.SKIPPED_REQUIRED_STEP, (call.id,), "NCR on a measurement whose gauge was not checked")
        )
    return out


def _approved_use_as_is(ncr: dict[str, Any]) -> bool:
    return ncr.get("status") == "approved" and ncr.get("disposition") == "use_as_is" and bool(ncr.get("approved_by"))


def _open_stop(events: list[dict[str, Any]]) -> int | None:
    for e in reversed(events):
        if e.get("event") == "first_article_check" and e.get("result") == "passed":
            return None
        if e.get("event") == "spindle_stop":
            return _int(e.get("duration_min"))
    return None


def _sentences(text: str) -> list[str]:
    return [x for x in re.split(r"(?<=[.!?])\s+", text) if x.strip()]


def _float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _int(value: Any) -> int:
    f = _float(value)
    return int(f) if f is not None else 0
