"""Refunds-specific error injectors (the generic ones live in gen/inject.py)."""

from __future__ import annotations

from rosetta_flow.gen.domains.base import DomainSpec
from rosetta_flow.gen.domains.refunds.policy import VOUCHER_LIMIT_CHF
from rosetta_flow.gen.inject import Injection, Injector, Job, answered_exchanges, next_agent_message
from rosetta_flow.gen.numbers import as_float, format_like, inside_identifier, number_tokens
from rosetta_flow.trace import ErrorType, Trace


def _vouchers(trace: Trace) -> list:
    return [e for e in answered_exchanges(trace) if e[1].tool == "apply_voucher" and e[3].status == "ok"]


def voucher_over_limit(job: Job) -> Injection | None:
    """Raise a goodwill voucher above the CHF 50 limit (R4) in the call, the result and the confirming message."""
    t = job.trace
    if not (options := _vouchers(t)):
        return None
    ci, call, ri, result = job.rng.choice(options)
    old = float(call.args["amount_chf"])
    new = float(job.rng.choice((60, 70, 75, 80, 90, 100, 120)))
    spans = list(t.spans)
    spans[ci] = call.model_copy(update={"args": {**call.args, "amount_chf": new}})
    spans[ri] = result.model_copy(update={"result": {**result.result, "amount_chf": new}})
    if (nxt := next_agent_message(t, ri)) is not None:
        mi, msg = nxt
        text = msg.text or ""
        hits = [t for t in number_tokens(text) if as_float(t.group()) == old and not inside_identifier(text, t)]
        # More than one mention: the other may be a different fact ("30 days" next to "CHF 30"); changing both would
        # plant a second error, changing one would leave the old amount standing.
        if len(hits) > 1:
            return None
        for tok in hits:
            text = text[: tok.start()] + format_like(tok.group(), new) + text[tok.end() :]
        spans[mi] = msg.model_copy(update={"text": text})
    return Injection(spans, [call.id], f"voucher CHF {old:.0f} -> {new:.0f} (limit {VOUCHER_LIMIT_CHF:.0f})")


def _voucher_ok(trace: Trace, spec: DomainSpec) -> bool:
    return bool(_vouchers(trace))


REFUNDS_INJECTORS = [
    Injector("voucher_over_limit", ErrorType.POLICY_VIOLATION, _voucher_ok, voucher_over_limit),
]
