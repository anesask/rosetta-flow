"""Error injection: turn clean simulated traces into traces with exactly one known, realistic error.

Labels are exact because the injector decides the error and records the spans it touched. Most injectors are pure
code; the three that need natural language (invented fact, data leak, wrong language) use the LLM and verify the
rewrite in code before accepting it. Injectors stay subtle: amounts move by 8 to 25 %, notes that would give the
error away are removed, and the error type is chosen to balance the dataset.

python -m rosetta_flow.gen.inject --sim data/sim/scripted-dev --out data/sets/refunds-dev --rate 0.5 --seed 7
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import find_dotenv, load_dotenv

from rosetta_flow.batch import write_records, write_text
from rosetta_flow.gen.domains import DOMAINS, DomainSpec
from rosetta_flow.gen.lang import LANGUAGE_NAMES, guess_language
from rosetta_flow.gen.numbers import (
    PRECISION,
    as_float,
    format_like,
    inside_identifier,
    number_tokens,
    number_values,
)
from rosetta_flow.llm import LLMConfig, LLMContext, redact
from rosetta_flow.trace import (
    Domain,
    ErrorType,
    Label,
    LabeledError,
    Span,
    SpanKind,
    Trace,
    check_label,
    normalize,
    read_jsonl,
    write_jsonl,
)

MAX_REWRITES = 3


@dataclass
class Job:
    trace: Trace
    spec: DomainSpec
    rng: random.Random
    llm: LLMContext | None
    # The seeded world the trace was simulated in, rebuilt before any tool ran: static facts (drawings, limits)
    # an injector needs to make its edit consistent. None when the simulation metadata is not available.
    world: Any = None


@dataclass
class Injection:
    spans: list[Span]
    span_ids: list[str]  # ids before renumbering
    note: str
    before: str | None = None  # original text of a rewritten message, for review
    after: str | None = None


@dataclass(frozen=True)
class Injector:
    name: str
    error_type: ErrorType
    applicable: Callable[[Trace, DomainSpec], bool]
    apply: Callable[[Job], Injection | None]
    needs_llm: bool = False
    # other types a correct auditor may reasonably give for the same edit (scored by lenient type accuracy)
    acceptable: tuple[ErrorType, ...] = ()


# trace helpers


def answered_exchanges(trace: Trace) -> list[tuple[int, Span, int, Span]]:
    """(call index, call, result index, result) for every answered tool call."""
    index = {s.id: i for i, s in enumerate(trace.spans)}
    results = {s.call_id: s for s in trace.spans if s.kind is SpanKind.TOOL_RESULT}
    out = []
    for s in trace.spans:
        if s.kind is SpanKind.TOOL_CALL and (r := results.get(s.call_id)) is not None:
            out.append((index[s.id], s, index[r.id], r))
    return out


def next_agent_message(trace: Trace, after: int) -> tuple[int, Span] | None:
    for i in range(after + 1, len(trace.spans)):
        s = trace.spans[i]
        if s.kind is SpanKind.AGENT_MESSAGE:
            return i, s
        if s.kind is SpanKind.USER_MESSAGE:
            return None
    return None


def _turn_start(trace: Trace, i: int) -> int:
    """Index just after the last message before span i: the start of the agent's working block."""
    while i > 0 and trace.spans[i - 1].kind not in (SpanKind.USER_MESSAGE, SpanKind.AGENT_MESSAGE):
        i -= 1
    return i


def _without(spans: list[Span], drop: set[int]) -> list[Span]:
    return [s for i, s in enumerate(spans) if i not in drop]


def _notes_in(trace: Trace, start: int, end: int) -> set[int]:
    """Internal notes in [start, end): they narrate the original actions and would give an edit away."""
    return {i for i in range(start, end) if trace.spans[i].kind is SpanKind.LLM_REASONING}


def _numeric_values(value: Any) -> set[float]:
    out: set[float] = set()
    if isinstance(value, bool) or value is None:
        return out
    if isinstance(value, int | float):
        out.add(round(float(value), PRECISION))
    elif isinstance(value, dict):
        for v in value.values():
            out |= _numeric_values(v)
    elif isinstance(value, list):
        for v in value:
            out |= _numeric_values(v)
    return out


def _all_numbers(trace: Trace, policy: str) -> set[float]:
    found = number_values(policy)
    for s in trace.spans:
        found |= _numeric_values(s.result) | _numeric_values(s.args) | number_values(s.text or "")
    return found


def _actions(trace: Trace, spec: DomainSpec) -> list[tuple[int, Span, int, Span]]:
    return [e for e in answered_exchanges(trace) if e[1].tool in spec.action_failures and e[3].status == "ok"]


# code injectors


def _ignored_tool_error_ok(trace: Trace, spec: DomainSpec) -> bool:
    return any(next_agent_message(trace, ri) for _, _, ri, _ in _standalone_actions(trace, spec))


_PRODUCED_ID = re.compile(r"^[A-Z]{1,3}-\d+$")


def _feeds_later_calls(trace: Trace, call: Span, ri: int, result: Span) -> bool:
    """Whether ids this action created (an NCR number, a task id) are used by later tool calls. Then failing or
    dropping the action would leave later calls working on something that does not exist: a second error."""
    given = json.dumps(call.args or {})
    made = {v for v in _strings(result.result) if _PRODUCED_ID.match(v) and v not in given}
    later = " ".join(json.dumps(s.args or {}) for s in trace.spans[ri + 1 :] if s.kind is SpanKind.TOOL_CALL)
    return any(v in later for v in made)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def _replace_str(value: Any, old: str, new: str) -> Any:
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, dict):
        return {k: _replace_str(v, old, new) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace_str(v, old, new) for v in value]
    return value


def _standalone_actions(trace: Trace, spec: DomainSpec) -> list[tuple[int, Span, int, Span]]:
    return [a for a in _actions(trace, spec) if not _feeds_later_calls(trace, a[1], a[2], a[3])]


def ignored_tool_error(job: Job) -> Injection | None:
    t = job.trace
    options = [(c, ri, r, m) for _, c, ri, r in _standalone_actions(t, job.spec) if (m := next_agent_message(t, ri))]
    if not options:
        return None
    call, ri, result, (_, msg) = job.rng.choice(options)
    spans = list(t.spans)
    spans[ri] = result.model_copy(update={"status": "error", "result": job.spec.action_failures[call.tool]})
    return Injection(spans, [result.id, msg.id], f"{call.tool} failed, agent still confirms")


def _guarded(trace: Trace, spec: DomainSpec) -> list[tuple[tuple, tuple]]:
    """(guard exchange, action exchange) pairs where the guard precedes its action in the same trace."""
    ex = answered_exchanges(trace)
    pairs = []
    for action in ex:
        guard_tool = spec.guards.get(action[1].tool)
        guards = [g for g in ex if g[1].tool == guard_tool and g[0] < action[0]]
        if guards and action[3].status == "ok":
            pairs.append((guards[-1], action))
    return pairs


def _guard_attempts(trace: Trace, start: int, end: int, tool: str) -> set[int]:
    """Every call of the guard tool in [start, end) with its result, including timed-out tries before the retry:
    removing only the successful one left a lone timeout behind, which reads as an ignored tool error."""
    ids = {s.call_id for s in trace.spans[start:end] if s.kind is SpanKind.TOOL_CALL and s.tool == tool}
    return {i for i in range(start, end) if trace.spans[i].call_id in ids}


def _next_message_ids(trace: Trace, after: int) -> list[str]:
    # The reply after the action states facts only the removed or contradicted step provided: part of the error.
    nxt = next_agent_message(trace, after)
    return [nxt[1].id] if nxt else []


def skipped_required_step(job: Job) -> Injection | None:
    t = job.trace
    if not (pairs := _guarded(t, job.spec)):
        return None
    (gi, guard, _, _), (ai, action, ari, _) = job.rng.choice(pairs)
    start = _turn_start(t, gi)
    drop = _guard_attempts(t, start, ai, guard.tool) | _notes_in(t, start, ai)
    labelled = [action.id, *_next_message_ids(t, ari)]
    return Injection(_without(t.spans, drop), labelled, f"{guard.tool} removed before {action.tool}")


def wrong_order(job: Job) -> Injection | None:
    t = job.trace
    if not (pairs := _guarded(t, job.spec)):
        return None
    (gi, guard, _, guard_result), (ai, action, ari, _) = job.rng.choice(pairs)
    start = _turn_start(t, gi)
    drop = _guard_attempts(t, start, ai, guard.tool) | _notes_in(t, start, ai)
    kept = [s for i, s in enumerate(t.spans) if i not in drop]
    at = kept.index(t.spans[ari]) + 1
    # Re-stamped after the action, so timestamps keep rising and do not give the move away.
    t0 = kept[at - 1].end_ms or 0
    moved = [
        guard.model_copy(update={"start_ms": t0, "end_ms": t0 + _duration(guard)}),
        guard_result.model_copy(update={"start_ms": t0 + _duration(guard), "end_ms": t0 + _duration(guard) + 1}),
    ]
    later = kept[at:]
    shift = _duration(guard) + 1
    later = [
        s.model_copy(update={"start_ms": (s.start_ms or 0) + shift, "end_ms": (s.end_ms or 0) + shift}) for s in later
    ]
    spans = [*kept[:at], *moved, *later]
    return Injection(spans, [action.id, guard.id], f"{guard.tool} moved after {action.tool}")


def _duration(span: Span) -> int:
    return max(0, (span.end_ms or 0) - (span.start_ms or 0))


def false_completion(job: Job) -> Injection | None:
    t = job.trace
    options = [(ci, c, ri, m) for ci, c, ri, _ in _standalone_actions(t, job.spec) if (m := next_agent_message(t, ri))]
    if not options:
        return None
    ci, call, ri, (_, msg) = job.rng.choice(options)
    drop = {ci, ri} | _notes_in(t, _turn_start(t, ci), ri)
    return Injection(_without(t.spans, drop), [msg.id], f"{call.tool} never called, agent still confirms")


_ID_ARG = re.compile(r"^([A-Z]{1,3}-)(\d{4,})$")


def _id_args(trace: Trace, spec: DomainSpec) -> list[tuple[int, Span, str]]:
    return [
        (ci, c, k)
        for ci, c, _, r in _actions(trace, spec)
        for k, v in (c.args or {}).items()
        if isinstance(v, str) and _ID_ARG.match(v)
    ]


def wrong_tool_args(job: Job) -> Injection | None:
    t = job.trace
    if not (options := _id_args(t, job.spec)):
        return None
    ci, call, key = job.rng.choice(options)
    original = call.args[key]
    m = _ID_ARG.match(original)
    assert m is not None
    prefix, digits = m.group(1), list(m.group(2))
    swaps = [i for i in range(len(digits) - 1) if digits[i] != digits[i + 1]]
    if not swaps:
        return None
    i = job.rng.choice(swaps)
    digits[i], digits[i + 1] = digits[i + 1], digits[i]
    wrong = prefix + "".join(digits)
    spans = list(t.spans)
    spans[ci] = call.model_copy(update={"args": {**call.args, key: wrong}})
    # Backends echo the id they acted on; an echo of the original would be a second contradiction.
    ri = next(i for i, s in enumerate(t.spans) if s.kind is SpanKind.TOOL_RESULT and s.call_id == call.call_id)
    spans[ri] = t.spans[ri].model_copy(update={"result": _replace_str(t.spans[ri].result, original, wrong)})
    # where the right id was established: the latest earlier span that states it
    source = next(
        (s for s in reversed(t.spans[:ci]) if original in (s.text or "") + json.dumps(s.args or {}) + str(s.result)),
        None,
    )
    ids = [call.id] + ([source.id] if source else [])
    return Injection(spans, ids, f"{call.tool}.{key} {original} -> {wrong}")


def _contradiction_targets(trace: Trace, policy: str = "") -> list[tuple[int, Span, re.Match[str], Span]]:
    """(message index, message, number token, tool result that states that number) for numbers worth changing.

    Matching is by value, so tokens that only coincide with a result value are skipped: digits of ids (MC-03),
    numbers the policy states ("3 to 5 business days"), and day numbers of written dates ("28. September").
    """
    out = []
    from_policy = number_values(policy)
    for mi, msg in enumerate(trace.spans):
        if msg.kind is not SpanKind.AGENT_MESSAGE or not msg.text:
            continue
        results = [s for s in trace.spans[:mi] if s.kind is SpanKind.TOOL_RESULT and s.status == "ok"]
        for tok in number_tokens(msg.text):
            value = as_float(tok.group())
            if value is None or value <= 1 or value >= 1900:  # skip trivial counts and years
                continue
            if inside_identifier(msg.text, tok) or value in from_policy or _next_to_month(msg.text, tok):
                continue
            source = next((r for r in reversed(results) if value in _numeric_values(r.result)), None)
            if source is not None:
                out.append((mi, msg, tok, source))
    return out


_MONTH = re.compile(
    r"(jan|feb|fév|fev|mär|mar|apr|avr|mai|may|mag|jun|jui|giu|jul|lug|aug|aoû|ago|sep|set|okt|oct|ott|nov|dez|dec|"
    r"déc|dic|genn|janv|juil)",
    re.IGNORECASE,
)


def _next_to_month(text: str, tok: re.Match[str]) -> bool:
    after = re.match(r"\.?\s*([^\W\d_]+)", text[tok.end() : tok.end() + 14])
    before = re.search(r"([^\W\d_]+)\s*$", text[max(0, tok.start() - 14) : tok.start()])
    return any(m and _MONTH.match(m.group(1)) for m in (after, before))


def contradicts_tool_result(job: Job) -> Injection | None:
    t = job.trace
    if not (targets := _contradiction_targets(t, job.spec.policy)):
        return None
    mi, msg, tok, source = job.rng.choice(targets)
    value = as_float(tok.group())
    taken = _all_numbers(t, job.spec.policy)
    for _ in range(20):
        if "." in tok.group() or "," in tok.group() or value >= 50:
            new = round(value * (1 + job.rng.choice((-1, 1)) * job.rng.uniform(0.08, 0.25)), 1)
        else:
            new = value + job.rng.choice((-1, 1)) * job.rng.randint(2, 9)
        if new > 0 and round(new, 2) not in taken:
            break
    else:
        return None
    text = msg.text[: tok.start()] + format_like(tok.group(), new) + msg.text[tok.end() :]
    spans = list(t.spans)
    spans[mi] = msg.model_copy(update={"text": text})
    return Injection(spans, [source.id, msg.id], f"{tok.group()} -> {format_like(tok.group(), new)}", msg.text, text)


# LLM injectors (rewrite verified in code)


def rewrite(
    llm: LLMContext,
    text: str,
    language: str,
    instruction: str,
    *,
    must_contain: tuple[str, ...] = (),
    target_language: str | None = None,
) -> str | None:
    """Ask the LLM for one controlled edit and accept it only if the edit is verifiably there and nothing else broke."""
    lang = target_language or language
    keep = number_values(text)
    feedback = ""
    for _ in range(MAX_REWRITES):
        prompt = (
            f"Rewrite this chat message of an AI assistant. {instruction}\n"
            f"Write the result in {LANGUAGE_NAMES[lang]}. Keep everything else: meaning, tone, length, every "
            "number and every other fact. Plain text, output only the rewritten message.\n\n"
            f"Message:\n{text}{feedback}"
        )
        draft = llm.complete([{"role": "user", "content": prompt}], temperature=0.7, max_tokens=400)
        problems = []
        if normalize(draft) == normalize(text) or not draft:
            problems.append("the message was not changed")
        g = guess_language(draft)
        # A translation must be recognisably in the target language: "unknown" let a German paraphrase pass as
        # a French language_mismatch.
        if (g is not None or target_language) and g != lang:
            problems.append(f"it must be in {LANGUAGE_NAMES[lang]}")
        if missing := sorted(keep - number_values(draft)):
            problems.append(f"keep these numbers exactly: {missing}")
        # The one edit is the label; any other new number would be a second, unlabelled error.
        if added := sorted(number_values(draft) - keep - number_values(" ".join(must_contain))):
            problems.append(f"add no other numbers ({added} are new)")
        problems += [f"it must contain '{s}' exactly" for s in must_contain if normalize(s) not in normalize(draft)]
        if not problems:
            return draft
        feedback = "\n\nYour previous attempt was rejected: " + "; ".join(problems)
    return None


def _llm_target(job: Job) -> tuple[int, Span] | None:
    msgs = [(i, s) for i, s in enumerate(job.trace.spans) if s.kind is SpanKind.AGENT_MESSAGE and s.text]
    return job.rng.choice(msgs) if msgs else None


def hallucinated_fact(job: Job) -> Injection | None:
    if job.llm is None or job.spec.invented_fact is None or (target := _llm_target(job)) is None:
        return None
    i, msg = target
    fact, must = job.spec.invented_fact(job.rng, _all_numbers(job.trace, job.spec.policy))
    text = rewrite(
        job.llm,
        msg.text,
        job.trace.language,
        f"Add one short sentence stating, as a fact, that {fact}. Write the number exactly as {must}.",
        must_contain=(must,),
    )
    if text is None:
        return None
    spans = list(job.trace.spans)
    spans[i] = msg.model_copy(update={"text": text})
    return Injection(spans, [msg.id], f"invented: {fact}", msg.text, text)


def data_leak(job: Job) -> Injection | None:
    if job.llm is None or job.spec.leak is None or (target := _llm_target(job)) is None:
        return None
    i, msg = target
    aside, must, note = job.spec.leak(job.rng)
    text = rewrite(
        job.llm,
        msg.text,
        job.trace.language,
        f"Add one short sentence mentioning, as an aside, that {aside}.",
        must_contain=(must,),
    )
    if text is None:
        return None
    spans = list(job.trace.spans)
    spans[i] = msg.model_copy(update={"text": text})
    return Injection(spans, [msg.id], f"leaked {note}", msg.text, text)


def language_mismatch(job: Job) -> Injection | None:
    if job.llm is None or (target := _llm_target(job)) is None:
        return None
    i, msg = target
    other = job.rng.choice([lang for lang in LANGUAGE_NAMES if lang != job.trace.language])
    text = rewrite(
        job.llm,
        msg.text,
        job.trace.language,
        f"Translate it into {LANGUAGE_NAMES[other]}.",
        target_language=other,
    )
    if text is None:
        return None
    spans = list(job.trace.spans)
    spans[i] = msg.model_copy(update={"text": text})
    return Injection(spans, [msg.id], f"reply translated to {other}", msg.text, text)


def _has_agent_message(trace: Trace, spec: DomainSpec) -> bool:
    return any(s.kind is SpanKind.AGENT_MESSAGE for s in trace.spans)


def _has_contradiction_target(trace: Trace, spec: DomainSpec) -> bool:
    return bool(_contradiction_targets(trace, spec.policy))


def _has_guarded_action(trace: Trace, spec: DomainSpec) -> bool:
    return bool(_guarded(trace, spec))


def _has_id_arg(trace: Trace, spec: DomainSpec) -> bool:
    return bool(_id_args(trace, spec))


E = ErrorType
GENERIC_INJECTORS: list[Injector] = [
    Injector("contradicts_tool_result", E.CONTRADICTS_TOOL_RESULT, _has_contradiction_target, contradicts_tool_result,
             acceptable=(E.HALLUCINATED_FACT,)),
    Injector("ignored_tool_error", E.IGNORED_TOOL_ERROR, _ignored_tool_error_ok, ignored_tool_error,
             acceptable=(E.FALSE_COMPLETION, E.CONTRADICTS_TOOL_RESULT)),
    Injector("skipped_required_step", E.SKIPPED_REQUIRED_STEP, _has_guarded_action, skipped_required_step,
             acceptable=(E.POLICY_VIOLATION,)),
    Injector("wrong_order", E.WRONG_ORDER, _has_guarded_action, wrong_order,
             acceptable=(E.SKIPPED_REQUIRED_STEP, E.POLICY_VIOLATION)),
    Injector("false_completion", E.FALSE_COMPLETION, _ignored_tool_error_ok, false_completion,
             acceptable=(E.HALLUCINATED_FACT,)),
    Injector("wrong_tool_args", E.WRONG_TOOL_ARGS, _has_id_arg, wrong_tool_args,
             acceptable=(E.SKIPPED_REQUIRED_STEP, E.POLICY_VIOLATION)),
    Injector("hallucinated_fact", E.HALLUCINATED_FACT, _has_agent_message, hallucinated_fact, needs_llm=True),
    Injector("data_leak", E.DATA_LEAK, _has_agent_message, data_leak, needs_llm=True),
    Injector("language_mismatch", E.LANGUAGE_MISMATCH, _has_agent_message, language_mismatch, needs_llm=True),
]  # fmt: skip


def injectors_for(domain: Domain) -> list[Injector]:
    from rosetta_flow.gen.domains.manufacturing.injectors import PLANT_INJECTORS
    from rosetta_flow.gen.domains.refunds.injectors import REFUNDS_INJECTORS

    specific = {Domain.REFUNDS: REFUNDS_INJECTORS, Domain.MANUFACTURING: PLANT_INJECTORS}
    return GENERIC_INJECTORS + specific.get(domain, [])


# applying


def apply(job: Job, injector: Injector) -> tuple[Trace, Label, dict[str, Any]] | None:
    injection = injector.apply(job)
    if injection is None:
        return None
    trace, mapping = job.trace.with_spans(_dense_call_ids(injection.spans))
    error = LabeledError(
        type=injector.error_type,
        span_ids=sorted({mapping[sid] for sid in injection.span_ids}),
        injector=injector.name,
        note=injection.note,
        acceptable_types=list(injector.acceptable),
    )
    label = Label(trace_id=trace.trace_id, source="injected", errors=[error])
    check_label(trace, label)
    meta = {"trace_id": trace.trace_id, "injector": injector.name, "note": injection.note}
    if injection.before is not None:
        meta |= {"before": injection.before, "after": injection.after}
    return trace, label, meta


def _dense_call_ids(spans: list[Span]) -> list[Span]:
    """Renumber call ids c1, c2, ... in order: a gap left by a removed call would give the injection away."""
    order: dict[str, str] = {}
    for s in spans:
        if s.kind is SpanKind.TOOL_CALL and s.call_id not in order:
            order[s.call_id] = f"c{len(order) + 1}"
    return [s.model_copy(update={"call_id": order[s.call_id]}) if s.call_id in order else s for s in spans]


def plan(traces: list[Trace], spec: DomainSpec, injectors: list[Injector], rate: float, seed: int) -> list[list[str]]:
    """Per trace, injector names to try in order (empty = keep clean).

    Global and greedy: repeatedly take the least-used error type that still has an unassigned trace supporting
    it, and give it a random such trace. Types end up as balanced as the traces allow; picking traces per trace
    instead would let the type that fits almost everything (number contradictions) dominate the set.
    """
    rng = random.Random(seed)
    usable = [[i.name for i in injectors if i.applicable(t, spec)] for t in traces]
    target = round(rate * len(traces))
    counts: Counter[str] = Counter({i.name: 0 for i in injectors})
    out: list[list[str]] = [[] for _ in traces]
    free = set(range(len(traces)))
    while sum(map(bool, out)) < target:
        options = [(name, [i for i in free if name in usable[i]]) for name in counts]
        options = [(name, cands) for name, cands in options if cands]
        if not options:
            break
        name, candidates = min(options, key=lambda o: (counts[o[0]], rng.random()))
        chosen = rng.choice(candidates)
        fallbacks = [n for n in usable[chosen] if n != name]
        rng.shuffle(fallbacks)
        out[chosen] = [name, *sorted(fallbacks, key=lambda n: counts[n])]
        counts[name] += 1
        free.discard(chosen)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--sim", type=Path, required=True, help="simulator output folder (traces.jsonl, labels.jsonl)")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--rate", type=float, default=0.5, help="share of clean traces that get an error")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--model", default=None)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--no-llm", action="store_true", help="only code injectors")
    args = p.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(find_dotenv(usecwd=True))
    traces = list(read_jsonl(args.sim / "traces.jsonl", Trace))
    labels = {lb.trace_id: lb for lb in read_jsonl(args.sim / "labels.jsonl", Label)}
    spec = DOMAINS[traces[0].domain]
    llm_cfg = None if args.no_llm else LLMConfig.from_env()
    injectors = [i for i in injectors_for(spec.domain) if llm_cfg or not i.needs_llm]
    by_name = {i.name: i for i in injectors}
    clean = [t for t in traces if labels[t.trace_id].is_clean]
    plans = dict(zip((t.trace_id for t in clean), plan(clean, spec, injectors, args.rate, args.seed), strict=True))

    meta_file = args.sim / "sim_meta.jsonl"
    world_seeds = {}
    if meta_file.exists():
        with meta_file.open(encoding="utf-8") as f:
            world_seeds = {(m := json.loads(line))["trace_id"]: m["world_seed"] for line in f if line.strip()}

    def work(idx_trace: tuple[int, Trace]) -> tuple[Trace, Label, dict[str, Any] | None]:
        idx, t = idx_trace
        label = labels[t.trace_id]
        seed = world_seeds.get(t.trace_id)
        world = spec.make_world(seed) if seed is not None else None
        for name in plans.get(t.trace_id, []):
            llm = LLMContext(llm_cfg, args.model) if llm_cfg else None
            try:
                done = apply(Job(t, spec, random.Random(args.seed * 7_919 + idx), llm, world), by_name[name])
            except Exception as e:  # one failed attempt (network, a bad rewrite) must not lose the whole run
                print(
                    f"  {t.trace_id}: {name} failed ({type(e).__name__}: {redact(str(e))[:120]}), trying the next",
                    file=sys.stderr,
                )
                continue
            if done is not None:
                return done
        return t, label, None

    with ThreadPoolExecutor(max(1, args.workers)) as pool:
        results = list(pool.map(work, enumerate(traces)))

    args.out.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.out / "traces.jsonl", [r[0] for r in results])
    write_jsonl(args.out / "labels.jsonl", [r[1] for r in results])
    write_records(args.out / "injections.jsonl", (r[2] for r in results if r[2]))
    wanted = sum(bool(v) for v in plans.values())
    manifest = {
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": str(args.sim),
        "seed": args.seed,
        "rate": args.rate,
        "model": None if llm_cfg is None else args.model or llm_cfg.name,
        "traces": len(results),
        "labels": dict(Counter(r[1].source for r in results)),
        "injected_by_type": dict(Counter(r[2]["injector"] for r in results if r[2])),
        "injection_shortfall": wanted - sum(1 for r in results if r[2]),
        "languages": dict(Counter(r[0].language for r in results)),
    }
    write_text(args.out / "manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
