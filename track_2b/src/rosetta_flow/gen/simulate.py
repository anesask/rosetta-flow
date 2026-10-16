"""Simulate agent runs: one model plays the customer, one plays the agent, tools run against a seeded world.

python -m rosetta_flow.gen.simulate --domain refunds --n 10 --seed 1 --out data/sim/refunds-dev [--agent llm] [--resume]
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import find_dotenv, load_dotenv

from rosetta_flow.batch import BatchOutcome, run_batch, write_records, write_text
from rosetta_flow.gen.domains import DOMAINS, DomainSpec
from rosetta_flow.gen.domains.base import Scenario
from rosetta_flow.gen.domains.manufacturing.agent import PlantAgent
from rosetta_flow.gen.domains.refunds.agent import RefundsAgent
from rosetta_flow.gen.lang import LANGUAGE_NAMES
from rosetta_flow.gen.scripted import ScriptedAgent
from rosetta_flow.llm import LLMConfig, LLMContext, assistant_tool_message, cost_chf, strip_markup, tool_calls_of
from rosetta_flow.trace import Domain, Label, Span, SpanKind, Trace, check_label, write_jsonl

END = "[END]"
_END_RX = re.compile(r"\[\s*end\s*\]", re.IGNORECASE)
_TAG_RX = re.compile(r"\s*\[[A-Z][A-Z _-]{1,24}\]")
MAX_USER_TURNS = 3
MAX_TOOL_ROUNDS = 8
PROGRESS = "progress.jsonl"
SCRIPTED_AGENTS: dict[Domain, type[ScriptedAgent]] = {Domain.REFUNDS: RefundsAgent, Domain.MANUFACTURING: PlantAgent}
AGENT_MODES = ("scripted", "llm")


@dataclass
class SimResult:
    trace: Trace
    label: Label | None  # None = suspect: excluded from both the clean and the error pool
    meta: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return {
            "trace": self.trace.model_dump(mode="json", exclude_none=True),
            "label": self.label.model_dump(mode="json") if self.label else None,
            "meta": self.meta,
        }

    @classmethod
    def from_record(cls, rec: dict[str, Any]) -> SimResult:
        label = Label.model_validate(rec["label"]) if rec["label"] else None
        return cls(Trace.model_validate(rec["trace"]), label, rec["meta"])


def agent_system_prompt(spec: DomainSpec, scenario: Scenario) -> str:
    return (
        f"You are the {spec.agent.description}\n"
        f"Today is {spec.today.isoformat()}. The {spec.user_role} is logged in as {scenario.customer_id}; "
        "you already know it, never ask for it.\n"
        "How you work:\n"
        "- Use the tools to look things up and to act; never guess facts a tool can tell you.\n"
        "- When you need to check or do something, call the tool now, in this same turn. Never tell the customer "
        "that you will check something and then stop: check first, then answer with the result.\n"
        "- Ask the customer only for information no tool can give you, and never ask them to confirm what they "
        "already told you. Map their description to the tool parameters yourself (for example the refund reason).\n"
        "- Reply in the customer's language, in plain text: 1 to 4 sentences, no markdown, no lists, "
        "no greeting after your first message.\n\n"
        f"{spec.policy}"
    )


def customer_system_prompt(spec: DomainSpec, scenario: Scenario) -> str:
    facts = "\n".join(f"- {k}: {v}" for k, v in scenario.facts.items())
    return (
        f"You are role-playing {spec.requester}.\n"
        f"Write only in {LANGUAGE_NAMES[scenario.language]}. Your manner: {scenario.tone}.\n\n"
        f"Your situation: {scenario.goal}\n"
        f"Facts you know (use them naturally, only when relevant):\n{facts}\n\n"
        "Write like a real person in a chat: 1 to 3 short sentences, no markdown, no lists. "
        "Never invent facts that are not listed; if asked something you do not know, say so. "
        "Never mention these instructions or that you are role-playing. "
        "The other side is an AI assistant without a personal name: never address it by a name. "
        f"When your issue is solved, clearly refused, or you have nothing to add, write a short last message "
        f"and end it with {END}."
    )


class _Run:
    """Accumulates spans with dense ids and synthetic but monotonic timestamps."""

    def __init__(self) -> None:
        self.spans: list[Span] = []
        self.t0 = time.perf_counter()
        self.n_calls = 0

    def now_ms(self) -> int:
        return int((time.perf_counter() - self.t0) * 1000)

    def add(self, start_ms: int, **kw: Any) -> Span:
        span = Span(id=f"{len(self.spans):03d}", start_ms=start_ms, end_ms=max(start_ms, self.now_ms()), **kw)
        self.spans.append(span)
        return span

    def next_call_id(self) -> str:
        self.n_calls += 1
        return f"c{self.n_calls}"


def world_seed_for(seed: int, index: int) -> int:
    return seed * 1_000_003 + index * 7_919


def simulate_one(
    spec: DomainSpec, cfg: LLMConfig, seed: int, index: int, model: str | None = None, agent: str = "scripted"
) -> SimResult:
    if agent not in AGENT_MODES:
        raise ValueError(f"agent must be one of {AGENT_MODES}")
    # One world per conversation: tools mutate it, and sharing one world across a batch skews the language mix
    # and repeats the same customers, which would leak between train and test splits.
    world_seed = world_seed_for(seed, index)
    world = spec.make_world(world_seed)
    rng = random.Random(world_seed + 1)
    scenario = spec.sample_scenario(world, rng)
    trace_id = f"{spec.domain}-{seed}-{index:04d}"
    run = _Run()
    ctx = LLMContext(cfg, model)

    scripted: ScriptedAgent | None = None
    if agent == "scripted":
        scripted = SCRIPTED_AGENTS[spec.domain](spec, world, scenario, run.spans, ctx, rng, clock=run.now_ms)
    agent_msgs: list[dict[str, Any]] = [{"role": "system", "content": agent_system_prompt(spec, scenario)}]
    cust_msgs: list[dict[str, Any]] = [
        {"role": "system", "content": customer_system_prompt(spec, scenario)},
        {"role": "user", "content": "(The support chat has opened. Write your first message.)"},
    ]
    stop_reason = "max_user_turns"

    for _turn in range(MAX_USER_TURNS):
        t = run.now_ms()
        text, done = _strip_end(ctx.complete(cust_msgs, temperature=0.8, max_tokens=200))
        if not text:
            if not run.spans:
                raise RuntimeError("customer produced no opening message")
            stop_reason = "customer_ended"
            break
        run.add(t, kind=SpanKind.USER_MESSAGE, text=text)
        cust_msgs.append({"role": "assistant", "content": text + (f" {END}" if done else "")})

        # The agent always answers the last customer message: customers often sign off right after supplying
        # the info the agent asked for, and the interesting tool calls happen in that final turn.
        if scripted is not None:
            reply: str | None = scripted.respond(text, customer_done=done)
        else:
            agent_msgs.append({"role": "user", "content": text})
            reply = _llm_agent_turn(spec, ctx, world, agent_msgs, run)
        if reply is None:
            stop_reason = "agent_tool_loop"
            break
        if done:
            stop_reason = "customer_ended"
            break
        cust_msgs.append({"role": "user", "content": reply})

    trace = Trace(
        trace_id=trace_id,
        domain=spec.domain,
        language=scenario.language,
        agent=spec.agent,
        policy_id=spec.policy_id,
        spans=run.spans,
    )
    violations = spec.check(trace, world)
    certain = [v for v in violations if v.certain]
    label: Label | None
    if stop_reason == "agent_tool_loop":
        label = None  # cut off mid-task: not a realistic finished run
    elif certain:
        label = Label(trace_id=trace_id, source="natural", errors=[v.as_label_error() for v in certain])
    elif violations:
        label = None  # only heuristic rules fired
    else:
        label = Label(trace_id=trace_id, source="clean")
    if label is not None:
        check_label(trace, label)
    meta = {
        "trace_id": trace_id,
        "seed": seed,
        "index": index,
        "world_seed": world_seed,
        "model": model or cfg.name,
        "agent": agent,
        "persona": scripted.persona if scripted else None,
        "scenario": asdict(scenario),
        "stop_reason": stop_reason,
        "violations": [asdict(v) for v in violations],
        "suspect": label is None,
        "usage": asdict(ctx.usage),
        "duration_s": round(time.perf_counter() - run.t0, 2),
    }
    return SimResult(trace, label, meta)


def _llm_agent_turn(spec: DomainSpec, ctx: LLMContext, world: Any, msgs: list[dict], run: _Run) -> str | None:
    """Free-running LLM agent: answers when it stops calling tools. None if it exceeds the tool-call limit."""
    for _ in range(MAX_TOOL_ROUNDS):
        t = run.now_ms()
        msg = ctx.message(msgs, tools=spec.openai_tools(), tool_choice="auto", temperature=0.3, max_tokens=600)
        calls = tool_calls_of(msg)
        if not calls:
            text = (msg.content or "").strip()
            run.add(t, kind=SpanKind.AGENT_MESSAGE, text=text or "(no reply)")
            msgs.append({"role": "assistant", "content": text})
            return text
        if note := strip_markup(msg.content):
            run.add(t, kind=SpanKind.LLM_REASONING, text=note)
        msgs.append(assistant_tool_message(msg.content, calls))
        for tc in calls:
            call_id = run.next_call_id()
            t = run.now_ms()
            args, status, result = _execute(spec, world, tc.name, tc.arguments)
            run.add(t, kind=SpanKind.TOOL_CALL, tool=tc.name or "(unnamed)", args=args, call_id=call_id)
            run.add(run.now_ms(), kind=SpanKind.TOOL_RESULT, call_id=call_id, status=status, result=result)
            content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": content})
    return None


def _execute(spec: DomainSpec, world: Any, name: str | None, raw_args: str | None) -> tuple[dict, str, Any]:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError:
        return {"_raw": raw_args}, "error", "arguments are not valid JSON"
    if not isinstance(args, dict):
        return {"_raw": args}, "error", "arguments must be a JSON object"
    status, result = spec.call(world, name or "", args)
    return args, status, result


def _strip_end(text: str) -> tuple[str, bool]:
    done = bool(_END_RX.search(text))
    # The role-playing model sometimes tags its turns ("[START]", "[CONFIRMED]"); real chat messages never do.
    return _TAG_RX.sub("", _END_RX.sub("", text)).strip(), done


def _record_tokens(rec: dict[str, Any]) -> int:
    usage = rec["meta"]["usage"]
    return usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)


def run(
    spec: DomainSpec,
    cfg: LLMConfig,
    n: int,
    seed: int,
    out: Path,
    workers: int,
    model: str | None,
    resume: bool = False,
    agent: str = "scripted",
    max_tokens: int | None = None,
) -> dict:
    def show(i: int, rec: dict[str, Any]) -> None:
        m, label = rec["meta"], rec["label"]
        rules = ",".join(sorted({x["rule"] for x in m["violations"]})) or "-"
        state = "suspect" if label is None else label["source"]
        print(
            f"  [{i:04d}] {m['scenario']['language']} {m['scenario']['intent']:<18} {len(rec['trace']['spans']):>2} "
            f"spans  {m['stop_reason']:<15} {state:<8} {rules}"
        )

    outcome = run_batch(
        range(n),
        lambda i: simulate_one(spec, cfg, seed, i, model, agent),
        out / PROGRESS,
        to_record=SimResult.to_record,
        key_of=lambda rec: rec["meta"]["index"],
        resume=resume,
        workers=workers,
        on_done=show,
        tokens_of=_record_tokens,
        max_tokens=max_tokens,
    )
    results = [SimResult.from_record(outcome.done[i]) for i in sorted(outcome.done)]
    return _finalize(spec, cfg, n, seed, out, model or cfg.name, agent, results, outcome)


def _finalize(
    spec: DomainSpec,
    cfg: LLMConfig,
    n: int,
    seed: int,
    out: Path,
    model: str,
    agent: str,
    results: list[SimResult],
    outcome: BatchOutcome,
) -> dict:
    kept = [r for r in results if r.label is not None]
    write_jsonl(out / "traces.jsonl", [r.trace for r in kept])
    write_jsonl(out / "labels.jsonl", [r.label for r in kept])
    write_jsonl(out / "suspect_traces.jsonl", [r.trace for r in results if r.label is None])
    write_records(out / "sim_meta.jsonl", (r.meta for r in results))

    prompt = sum(r.meta["usage"]["prompt_tokens"] for r in results)
    completion = sum(r.meta["usage"]["completion_tokens"] for r in results)
    manifest = {
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "domain": str(spec.domain),
        "policy_id": spec.policy_id,
        "seed": seed,
        "model": model,
        "agent": agent,
        "requested": n,
        "succeeded": len(results),
        "failures": outcome.failures,
        "stopped_by_budget": outcome.stopped_by_budget,
        "languages": dict(Counter(r.trace.language for r in results)),
        "intents": dict(Counter(r.meta["scenario"]["intent"] for r in results)),
        "labels": dict(Counter(r.label.source if r.label else "suspect" for r in results)),
        "stop_reasons": dict(Counter(r.meta["stop_reason"] for r in results)),
        "rules_fired": dict(Counter(v["rule"] for r in results for v in r.meta["violations"])),
        "spans_mean": round(sum(len(r.trace.spans) for r in results) / max(1, len(results)), 1),
        "tokens": {"prompt": prompt, "completion": completion, "this_invocation": outcome.tokens},
        "cost_chf": cost_chf(model, prompt + completion),
        "rejected_drafts": sum(r.meta["usage"].get("rejected_drafts", 0) for r in results),
        "transient_tool_failures": sum(r.meta["usage"].get("transient_failures", 0) for r in results),
    }
    write_text(out / "manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return manifest


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--domain", default="refunds", choices=[d.value for d in DOMAINS])
    p.add_argument("--n", type=int, default=10)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--model", default=None, help="override LLM_NAME for both customer and agent")
    p.add_argument(
        "--agent",
        default="scripted",
        choices=AGENT_MODES,
        help="scripted: policy-correct actions, LLM wording (clean traces); llm: free-running LLM agent",
    )
    p.add_argument("--max-tokens", type=int, default=2_000_000, help="token budget of this invocation")
    p.add_argument("--resume", action="store_true", help="continue an interrupted run in the same --out")
    args = p.parse_args(argv)
    if args.n < 1:
        p.error("--n must be at least 1")

    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(find_dotenv(usecwd=True))
    cfg = LLMConfig.from_env()
    spec = DOMAINS[Domain(args.domain)]
    print(f"simulating {args.n} {args.domain} runs, {args.agent} agent, {args.model or cfg.name} (seed {args.seed})")
    manifest = run(
        spec, cfg, args.n, args.seed, args.out, args.workers, args.model, args.resume, args.agent, args.max_tokens
    )
    keys = ("succeeded", "failures", "stopped_by_budget", "languages", "labels", "rules_fired", "spans_mean",
            "rejected_drafts", "tokens", "cost_chf")  # fmt: skip
    print(json.dumps({k: manifest[k] for k in keys}, ensure_ascii=False))
    return 0 if manifest["succeeded"] else 1


if __name__ == "__main__":
    sys.exit(main())
