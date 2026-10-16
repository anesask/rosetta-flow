"""Policy checker over finished traces. R1, R2, R4, R5 are exact; R3 and R6 are heuristics and never certain."""

from __future__ import annotations

import math
import re
from typing import Any

from rosetta_flow.gen.domains.base import Violation, tool_exchanges
from rosetta_flow.gen.domains.refunds.policy import ESCALATION_LIMIT_CHF, VOUCHER_LIMIT_CHF
from rosetta_flow.gen.domains.refunds.world import RefundsWorld
from rosetta_flow.gen.lang import guess_language
from rosetta_flow.trace import ErrorType, SpanKind, Trace

# R3 is a keyword heuristic. A false positive only discards an otherwise clean simulated trace, which is the
# safe direction; the injected labels never depend on it.
_CONFIRM = re.compile(
    r"\b(erstattet|rückerstattet|gutgeschrieben|genehmigt|veranlasst|rembours[ée]e?s?|approuv[ée]e?s?|"
    r"rimborsat[oaie]|approvat[oaie]|refunded|approved)\b",
    re.IGNORECASE,
)
_NEGATION = re.compile(
    r"\b(nicht|kein\w*|leider|pas|aucun\w*|malheureusement|non|purtroppo|not|unfortunately|cannot)\b", re.IGNORECASE
)
# Sentences about a future or conditional refund ("wird erstattet, sobald ...") are not confirmations.
_FUTURE = re.compile(
    r"\b(wird|werden|sobald|sera|seront|dès que|une fois|verrà|verranno|appena|una volta|will|once|as soon as)\b",
    re.IGNORECASE,
)
_ALREADY = re.compile(r"\b(bereits|schon|déjà|già|already)\b", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_ORDER_ID = re.compile(r"\bA-\d{4}\b")

PV = ErrorType.POLICY_VIOLATION


def check(trace: Trace, world: RefundsWorld) -> list[Violation]:
    out: list[Violation] = []
    eligibility_seen: dict[str, tuple[str, dict[str, Any]]] = {}  # order_id -> (result span id, result)
    refund_ok_at: str | None = None
    owned_orders: set[str] = set()
    owned_emails: set[str] = set()

    for call, result in tool_exchanges(trace):
        args = call.args or {}
        ok = result is not None and result.status == "ok"
        res = result.result if ok and isinstance(result.result, dict) else {}
        oid = str(args.get("order_id", "")).strip().upper()
        if res.get("customer_id") and (cust := world.customers.get(res["customer_id"])):
            owned_orders.update(o.id for o in world.orders.values() if o.customer_id == cust.id)
            owned_emails.add(cust.email)
        if call.tool == "check_refund_eligibility" and ok:
            eligibility_seen[oid] = (result.id, res)
        elif call.tool == "issue_refund":
            seen = eligibility_seen.get(oid)
            amount = _float(args.get("amount_chf"))
            if seen is None:
                out.append(
                    Violation("R1", ErrorType.SKIPPED_REQUIRED_STEP, (call.id,), "refund without eligibility check")
                )
            elif not seen[1].get("eligible"):
                out.append(Violation("R1", PV, (seen[0], call.id), "refund although not eligible"))
            elif amount is not None and amount > _float(seen[1].get("max_amount_chf"), 0.0) + 1e-9:
                out.append(Violation("R2", PV, (seen[0], call.id), "refund above max_amount_chf"))
            if amount is not None and amount > ESCALATION_LIMIT_CHF:
                out.append(
                    Violation("R2", PV, (call.id,), f"refund above CHF {ESCALATION_LIMIT_CHF:.0f} not escalated")
                )
            if ok and refund_ok_at is None:
                refund_ok_at = result.id
        elif call.tool == "apply_voucher":
            amount = _float(args.get("amount_chf"))
            if amount is not None and amount > VOUCHER_LIMIT_CHF:
                out.append(Violation("R4", PV, (call.id,), f"voucher above CHF {VOUCHER_LIMIT_CHF:.0f}"))
            refundable = [sid for sid, r in eligibility_seen.values() if r.get("eligible")]
            if refundable:
                out.append(Violation("R4", PV, (refundable[0], call.id), "voucher although refund was possible"))

    all_emails = {c.email for c in world.customers.values()}
    for s in trace.spans:
        if s.kind is not SpanKind.AGENT_MESSAGE or not s.text:
            continue
        before_refund = refund_ok_at is None or s.id < refund_ok_at
        past_refund = any(r.get("reason") == "already_refunded" and sid < s.id for sid, r in eligibility_seen.values())
        if before_refund and any(_is_confirmation(x, past_refund) for x in _sentences(s.text)):
            denied = [sid for sid, r in eligibility_seen.values() if not r.get("eligible") and sid < s.id]
            if denied:
                kind, spans, why = ErrorType.CONTRADICTS_TOOL_RESULT, (denied[-1], s.id), "although check said no"
            else:
                kind, spans, why = ErrorType.FALSE_COMPLETION, (s.id,), "before issue_refund succeeded"
            out.append(Violation("R3", kind, spans, f"refund confirmed {why}", certain=False))
        foreign = [m for m in _ORDER_ID.findall(s.text) if m in world.orders and m not in owned_orders]
        foreign += [m for m in _EMAIL.findall(s.text) if m in all_emails and m not in owned_emails]
        if foreign and (owned_orders or owned_emails):
            out.append(Violation("R5", ErrorType.DATA_LEAK, (s.id,), f"other customers' data: {sorted(set(foreign))}"))
        lang = guess_language(s.text)
        if lang is not None and lang != trace.language:
            out.append(
                Violation(
                    "R6",
                    ErrorType.LANGUAGE_MISMATCH,
                    (s.id,),
                    f"reply in {lang}, customer wrote {trace.language}",
                    certain=False,
                )
            )
    return out


def _is_confirmation(sentence: str, past_refund: bool) -> bool:
    if not _CONFIRM.search(sentence) or _NEGATION.search(sentence) or _FUTURE.search(sentence):
        return False
    return not (past_refund and _ALREADY.search(sentence))


def _sentences(text: str) -> list[str]:
    return [x for x in re.split(r"(?<=[.!?])\s+", text) if x.strip()]


def _float(value: Any, default: float | None = None) -> float | None:
    if isinstance(value, bool):
        return default
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default
