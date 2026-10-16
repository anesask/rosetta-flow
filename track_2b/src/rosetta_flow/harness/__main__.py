"""Audit a JSONL file of traces.

python -m rosetta_flow.harness --traces data/sim/refunds-dev/traces.jsonl [--out results/<name>] [--model NAME]
                               [--limit N] [--workers 4] [--policy-file policy.md] [--resume]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from rosetta_flow.batch import run_batch, write_records, write_text
from rosetta_flow.gen.domains import DOMAINS
from rosetta_flow.harness.audit import HARNESS_VARIANTS, AuditResult, HarnessOptions, audit, summarize
from rosetta_flow.harness.single import audit_single
from rosetta_flow.llm import LLMConfig, LLMContext, cost_chf
from rosetta_flow.trace import Trace, index_by, read_jsonl


def policy_for(trace: Trace, policy_file: Path | None) -> str:
    if policy_file is not None:
        return policy_file.read_text(encoding="utf-8")
    spec = DOMAINS.get(trace.domain)
    if spec is None or spec.policy_id != trace.policy_id:
        raise SystemExit(f"no built-in policy '{trace.policy_id}' for {trace.trace_id}; pass --policy-file")
    return spec.policy


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--traces", type=Path, required=True)
    p.add_argument("--out", type=Path, default=None, help="default: results/audit-<UTC timestamp>")
    p.add_argument("--model", default=None, help="override LLM_NAME, e.g. swiss-ai/Apertus-v1.5-8B")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--policy-file", type=Path, default=None, help="policy text for traces from outside our domains")
    p.add_argument("--max-tokens", type=int, default=5_000_000, help="token budget of this invocation")
    p.add_argument("--variant", choices=sorted(HARNESS_VARIANTS), default="default", help="harness variant (ablations)")
    p.add_argument(
        "--mode",
        choices=("investigate", "single"),
        default="investigate",
        help="investigate: tools over the trace (B1/B2/B3); single: whole trace in one prompt, no tools (B0)",
    )
    p.add_argument("--resume", action="store_true")
    args = p.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(find_dotenv(usecwd=True))
    cfg = LLMConfig.from_env()
    model = args.model or cfg.name
    traces = list(read_jsonl(args.traces, Trace))[: args.limit]
    by_id = index_by(traces, lambda t: t.trace_id, args.traces)
    policies = {t.trace_id: policy_for(t, args.policy_file) for t in traces}  # fail fast, before any API call
    out = args.out or Path("results") / f"audit-{datetime.now(UTC):%Y%m%d-%H%M%S}"
    print(f"auditing {len(traces)} traces with {model} -> {out}")

    options = HarnessOptions.named(args.variant)
    run_one = audit_single if args.mode == "single" else partial(audit, options=options)
    outcome = run_batch(
        list(by_id),
        lambda tid: run_one(by_id[tid], policies[tid], LLMContext(cfg, args.model)),
        out / "progress.jsonl",
        to_record=AuditResult.to_record,
        key_of=lambda rec: rec["trace_id"],
        resume=args.resume,
        workers=args.workers,
        on_done=lambda tid, rec: print(f"  {tid}  {summarize(AuditResult.from_record(rec))}"),
        tokens_of=lambda rec: rec["usage"].get("prompt_tokens", 0) + rec["usage"].get("completion_tokens", 0),
        max_tokens=args.max_tokens,
    )
    results = [AuditResult.from_record(outcome.done[tid]) for tid in by_id if tid in outcome.done]
    write_records(out / "audits.jsonl", (r.to_record() for r in results))

    reports = [r.report for r in results if r.report]
    evidence = [e.verified for r in results for e in r.evidence]
    tokens = sum(r.usage["prompt_tokens"] + r.usage["completion_tokens"] for r in results)
    chf = cost_chf(model, tokens)
    summary = {
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "traces_file": str(args.traces),
        "model": model,
        "mode": args.mode,
        "variant": args.variant,
        "audited": len(results),
        "failures": outcome.failures,
        "stopped_by_budget": outcome.stopped_by_budget,
        "no_report": dict(Counter(r.failure for r in results if r.failure)),
        "report_fallbacks": dict(Counter(r.report_fallback for r in results if r.report_fallback)),
        "verdicts": dict(Counter(r.verdict for r in reports)),
        "findings_by_type": dict(Counter(f.error_type.value for r in reports for f in r.findings)),
        "evidence_verified_rate": round(sum(evidence) / len(evidence), 3) if evidence else None,
        "tool_calls_mean": round(sum(r.tool_calls for r in results) / max(1, len(results)), 1),
        "duration_s_mean": round(sum(r.duration_s for r in results) / max(1, len(results)), 1),
        "tokens": {
            "prompt": sum(r.usage["prompt_tokens"] for r in results),
            "completion": sum(r.usage["completion_tokens"] for r in results),
            "per_trace": round(tokens / max(1, len(results))),
            "this_invocation": outcome.tokens,
        },
        "cost_chf": chf,
        "chf_per_1000_traces": round(chf / max(1, len(results)) * 1000, 2) if chf is not None else None,
    }
    write_text(out / "summary.json", json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("created", "traces_file")}, ensure_ascii=False))
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
