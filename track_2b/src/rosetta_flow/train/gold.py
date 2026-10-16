"""Collect gold investigations: the reference auditor (70B) audits training traces, and only investigations that
reach the labelled answer are kept (rejection sampling). The kept transcripts are what the on-prem 8B imitates.

python -m rosetta_flow.train.gold --set data/sets/refunds-train --out data/gold/refunds-train [--attempts 3]
                                  [--model swiss-ai/Apertus-v1.5-70B] [--workers 6] [--max-tokens N] [--resume]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import find_dotenv, load_dotenv

from rosetta_flow.batch import run_batch, write_records, write_text
from rosetta_flow.eval.metrics import investigation_matches
from rosetta_flow.harness.__main__ import policy_for
from rosetta_flow.harness.audit import audit
from rosetta_flow.llm import LLMConfig, LLMContext, cost_chf
from rosetta_flow.trace import Label, Trace, index_by, read_jsonl

REFERENCE_MODEL = "swiss-ai/Apertus-v1.5-70B"
# The first attempt is the reference auditor's normal behaviour; later ones explore, so a trace it misses at
# temperature 0 can still yield one correct investigation.
TEMPERATURES = (0.0, 0.7, 0.7, 0.7)


def collect(trace: Trace, label: Label, policy: str, cfg: LLMConfig, model: str, attempts: int) -> dict[str, Any]:
    tried = []
    for i in range(attempts):
        temperature = TEMPERATURES[min(i, len(TEMPERATURES) - 1)]
        result = audit(trace, policy, LLMContext(cfg, model), temperature=temperature)
        ok, reason = investigation_matches(result, label)
        usage = result.usage
        tried.append({"attempt": i, "temperature": temperature, "kept": ok, "reason": reason,
                      "tokens": usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)})  # fmt: skip
        if ok:
            return {"trace_id": trace.trace_id, "kept": True, "attempts": tried, "audit": result.to_record()}
    return {"trace_id": trace.trace_id, "kept": False, "attempts": tried, "audit": None}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--set", type=Path, required=True, help="dataset folder with traces.jsonl and labels.jsonl")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--model", default=REFERENCE_MODEL)
    p.add_argument("--attempts", type=int, default=3)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--max-tokens", type=int, default=20_000_000, help="token budget of this invocation")
    p.add_argument("--resume", action="store_true")
    args = p.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(find_dotenv(usecwd=True))
    cfg = LLMConfig.from_env()
    traces = index_by(list(read_jsonl(args.set / "traces.jsonl", Trace))[: args.limit], lambda t: t.trace_id, args.set)
    labels = index_by(read_jsonl(args.set / "labels.jsonl", Label), lambda lb: lb.trace_id, args.set)
    policies = {tid: policy_for(t, None) for tid, t in traces.items()}
    print(f"collecting gold investigations for {len(traces)} traces with {args.model} -> {args.out}")

    def report(tid: str, rec: dict[str, Any]) -> None:
        last = rec["attempts"][-1]
        print(f"  {tid}  {'kept' if rec['kept'] else 'none'} after {len(rec['attempts'])}  {last['reason']}")

    outcome = run_batch(
        list(traces),
        lambda tid: collect(traces[tid], labels[tid], policies[tid], cfg, args.model, args.attempts),
        args.out / "progress.jsonl",
        to_record=lambda rec: rec,
        key_of=lambda rec: rec["trace_id"],
        resume=args.resume,
        workers=args.workers,
        on_done=report,
        tokens_of=lambda rec: sum(a["tokens"] for a in rec["attempts"]),
        max_tokens=args.max_tokens,
    )
    records = [outcome.done[tid] for tid in traces if tid in outcome.done]
    gold = [
        {"trace_id": r["trace_id"], "domain": traces[r["trace_id"]].domain, "language": traces[r["trace_id"]].language,
         "label": labels[r["trace_id"]].model_dump(mode="json"), "attempt": r["attempts"][-1]["attempt"],
         "audit": r["audit"]}
        for r in records if r["kept"]
    ]  # fmt: skip
    write_records(args.out / "gold.jsonl", gold)
    write_text(args.out / "summary.json", json.dumps(_summary(args, records, labels, outcome), indent=2) + "\n")
    print(json.dumps(_summary(args, records, labels, outcome)["kept"], ensure_ascii=False))
    return 0 if records else 1


def _summary(args: argparse.Namespace, records: list[dict], labels: dict[str, Label], outcome) -> dict[str, Any]:
    by_kind: dict[str, Counter] = defaultdict(Counter)
    reasons: Counter = Counter()
    for r in records:
        label = labels[r["trace_id"]]
        kind = "clean" if label.is_clean else (label.errors[0].injector or label.errors[0].type.value)
        by_kind[kind]["kept" if r["kept"] else "rejected"] += 1
        reasons.update(a["reason"] for a in r["attempts"] if not a["kept"])
    tokens = sum(a["tokens"] for r in records for a in r["attempts"])
    kept = sum(r["kept"] for r in records)
    return {
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "set": str(args.set),
        "model": args.model,
        "attempts_max": args.attempts,
        "traces": len(records),
        "failures": outcome.failures,
        "stopped_by_budget": outcome.stopped_by_budget,
        "kept": {"total": kept, "rate": round(kept / max(1, len(records)), 3)},
        "kept_by_kind": {k: dict(v) for k, v in sorted(by_kind.items())},
        "kept_at_attempt": dict(Counter(r["attempts"][-1]["attempt"] for r in records if r["kept"])),
        "rejection_reasons": dict(reasons.most_common()),
        "tokens": tokens,
        "cost_chf": cost_chf(args.model, tokens),
    }


if __name__ == "__main__":
    sys.exit(main())
