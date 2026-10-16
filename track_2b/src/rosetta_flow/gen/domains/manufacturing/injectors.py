"""Manufacturing-specific error injectors (the generic ones live in gen/inject.py).

Every edit keeps the trace self-consistent except for the one error it plants, and every span that states the
error is labelled, so the label is exact. An injector that cannot guarantee that for a trace declines it.
"""

from __future__ import annotations

import re

from rosetta_flow.gen.domains.base import DomainSpec
from rosetta_flow.gen.domains.manufacturing.policy import FIRST_PIECES_AFTER_STOP
from rosetta_flow.gen.domains.manufacturing.tools import get_drawing
from rosetta_flow.gen.inject import Injection, Injector, Job, answered_exchanges, next_agent_message
from rosetta_flow.gen.numbers import as_float, format_like, inside_identifier, number_tokens
from rosetta_flow.trace import ErrorType, Span, SpanKind, Trace

E = ErrorType
# Counts the verbaliser may have written as a word; a digit edit would then leave the old count standing.
_THREE_AS_WORD = re.compile(r"\b(drei|trois|tre|three)\b", re.IGNORECASE)


def _ok(trace: Trace, tool: str) -> list[tuple[int, Span, int, Span]]:
    return [x for x in answered_exchanges(trace) if x[1].tool == tool and x[3].status == "ok"]


def replace_numbers(text: str, old: float, new: float) -> tuple[str, int]:
    """Every mention of `old` written as a number, outside ids (MC-03 keeps its 3); returns (text, replacements)."""
    hits = [t for t in number_tokens(text) if as_float(t.group()) == old and not inside_identifier(text, t)]
    for tok in reversed(hits):
        text = text[: tok.start()] + format_like(tok.group(), new) + text[tok.end() :]
    return text, len(hits)


def _notes_between(trace: Trace, start: int, end: int) -> set[int]:
    return {i for i in range(start, end) if trace.spans[i].kind is SpanKind.LLM_REASONING}


def _message_after(trace: Trace, index: int) -> list[Span]:
    nxt = next_agent_message(trace, index)
    return [nxt[1]] if nxt else []


# release without approval (Q4)


def _released_after_approval(trace: Trace) -> list[tuple[int, Span, Span, int]]:
    releases = _ok(trace, "release_lot")
    out = []
    for _, _, ri, result in _ok(trace, "get_ncr"):
        r = result.result
        if r.get("status") == "approved" and r.get("disposition") == "use_as_is":
            later = [(c, rri) for ci, c, rri, _ in releases if ci > ri and c.args.get("lot_id") == r.get("lot_id")]
            if later:
                out.append((ri, result, *later[0]))
    return out


def release_without_approval(job: Job) -> Injection | None:
    """The NCR still awaits approval, yet the agent releases the lot and says it was approved."""
    if not (options := _released_after_approval(job.trace)):
        return None
    ri, result, release, release_ri = job.rng.choice(options)
    spans = list(job.trace.spans)
    spans[ri] = result.model_copy(
        update={"result": {**result.result, "status": "awaiting_approval", "approved_by": None, "approved_on": None}}
    )
    # The confirmation names the approver and date the NCR no longer shows: part of the same error.
    labelled = [result.id, release.id, *(m.id for m in _message_after(job.trace, release_ri))]
    return Injection(spans, labelled, f"{result.result['ncr_id']} not approved, lot released anyway")


# wrong drawing revision (Q2)


def _drawing_lookups(trace: Trace) -> list[tuple[int, Span, int, Span, Span]]:
    """(work order result index, wo result, drawing call index, call, drawing result) on an older-revision order."""
    out = []
    for _, _, wri, wo in _ok(trace, "get_work_order"):
        for ci, call, _, drawing in _ok(trace, "get_drawing"):
            r = drawing.result
            if ci > wri and r["part_no"] == wo.result["part_no"] and r["revision"] != r["current_revision"]:
                out.append((wri, wo, ci, call, drawing))
    return out


def _measured(trace: Trace, after: int) -> str | None:
    for s in trace.spans[after:]:
        if s.kind is SpanKind.TOOL_CALL and s.tool in ("record_inspection", "request_remeasurement"):
            return str((s.args or {}).get("characteristic", "")).upper() or None
    return None


def _limits(drawing: dict) -> dict[str, tuple[float, float]]:
    return {c["id"]: (c["lower_mm"], c["upper_mm"]) for c in drawing["characteristics"]}


def wrong_revision(job: Job) -> Injection | None:
    """Limits looked up on the latest drawing instead of the work order's revision.

    The looked-up result is the real current drawing (from the seeded world), and only traces where the measured
    characteristic has the same limits in both revisions qualify: the verdict stays right, only the lookup and
    the reply that names the revision are wrong. Without the world the injector declines.
    """
    if job.world is None or not (options := _drawing_lookups(job.trace)):
        return None
    t = job.trace
    for wri, wo, ci, call, drawing in job.rng.sample(options, len(options)):
        current = drawing.result["current_revision"]
        real = get_drawing(job.world, drawing.result["part_no"], current)
        char = _measured(t, ci)
        if char is None or _limits(real).get(char) != _limits(drawing.result).get(char):
            continue
        di = t.spans.index(drawing)
        spans = list(t.spans)
        spans[ci] = call.model_copy(update={"args": {**call.args, "revision": current}})
        spans[di] = drawing.model_copy(update={"result": real})
        labelled = [wo.id, call.id, *(m.id for m in _message_after(t, di))]
        # Notes that reason about "the work order's revision" would give the edit away.
        drop = _notes_between(t, wri + 1, ci)
        spans = [s for i, s in enumerate(spans) if i not in drop]
        return Injection(
            spans, labelled, f"drawing rev {current} used, work order on rev {wo.result['drawing_revision']}"
        )
    return None


# NCR scope too small (Q3)


def scope_too_small(job: Job) -> Injection | None:
    t = job.trace
    ncrs = _ok(t, "create_ncr")
    records = _ok(t, "get_inspection_records")
    if not ncrs or not records:
        return None
    ci, call, ri, result = job.rng.choice(ncrs)
    rec_result = next((r for _, _, _, r in reversed(records) if t.spans.index(r) < ci), None)
    if rec_result is None:
        return None
    old_from, to = int(call.args["scope_from_unit"]), int(call.args["scope_to_unit"])
    old_units = to - old_from + 1
    if old_units < 4:
        return None
    new_from = old_from + job.rng.randint(max(2, old_units // 3), old_units - 2)
    new_units = to - new_from + 1
    spans = list(t.spans)
    spans[ci] = call.model_copy(update={"args": {**call.args, "scope_from_unit": new_from}})
    spans[ri] = result.model_copy(
        update={"result": {**result.result, "scope_from_unit": new_from, "scope_units": new_units}}
    )
    if (nxt := next_agent_message(t, ri)) is not None:
        mi, msg = nxt
        text, _ = replace_numbers(msg.text or "", old_from, new_from)
        text, _ = replace_numbers(text, old_units, new_units)
        spans[mi] = msg.model_copy(update={"text": text})
    drop = {i for i in _notes_between(t, t.spans.index(rec_result), ci) if str(old_from) in (t.spans[i].text or "")}
    spans = [s for i, s in enumerate(spans) if i not in drop]
    note = f"scope from unit {old_from} -> {new_from} (last pass {rec_result.result['last_pass_unit']})"
    return Injection(spans, [rec_result.id, call.id], note)


# too few first pieces after a long stop (Q6)


def too_few_first_pieces(job: Job) -> Injection | None:
    t = job.trace
    if not (options := _ok(t, "request_first_article_check")):
        return None
    ci, call, ri, result = job.rng.choice(options)
    new = 1
    spans = list(t.spans)
    spans[ci] = call.model_copy(update={"args": {**call.args, "pieces": new}})
    spans[ri] = result.model_copy(update={"result": {**result.result, "pieces": new}})
    if (nxt := next_agent_message(t, ri)) is not None:
        mi, msg = nxt
        text, n = replace_numbers(msg.text or "", FIRST_PIECES_AFTER_STOP, new)
        # At most one mention, as a digit: a count written as a word, or a second "3" that may be something else,
        # would leave the old count standing or change an unrelated number.
        if n > 1 or _THREE_AS_WORD.search(msg.text or ""):
            return None
        spans[mi] = msg.model_copy(update={"text": text})
    return Injection(spans, [call.id], f"first-article check for {new} piece instead of {FIRST_PIECES_AFTER_STOP}")


def _has(tool: str):
    return lambda trace, spec: bool(_ok(trace, tool))


def _has_ncr_scope(trace: Trace, spec: DomainSpec) -> bool:
    return bool(_ok(trace, "create_ncr")) and bool(_ok(trace, "get_inspection_records"))


PLANT_INJECTORS = [
    Injector(
        "release_without_approval",
        E.POLICY_VIOLATION,
        lambda t, s: bool(_released_after_approval(t)),
        release_without_approval,
        acceptable=(E.CONTRADICTS_TOOL_RESULT, E.HALLUCINATED_FACT),
    ),
    Injector(
        "wrong_revision",
        E.WRONG_TOOL_ARGS,
        lambda t, s: bool(_drawing_lookups(t)),
        wrong_revision,
        acceptable=(E.POLICY_VIOLATION,),
    ),
    Injector(
        "scope_too_small",
        E.POLICY_VIOLATION,
        _has_ncr_scope,
        scope_too_small,
        acceptable=(E.CONTRADICTS_TOOL_RESULT, E.WRONG_TOOL_ARGS),
    ),
    Injector(
        "too_few_first_pieces",
        E.POLICY_VIOLATION,
        _has("request_first_article_check"),
        too_few_first_pieces,
        acceptable=(E.WRONG_TOOL_ARGS,),
    ),
]
