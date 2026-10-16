"""Verify mode for the confirmer: instead of investigating the run again from scratch, the large model gets the whole
run, the policy and the screener's findings, and checks them: keep a finding whose steps really show the error,
correct its steps, type or quotes when the error is real but cited wrongly, drop it when the agent did nothing
wrong. No tools are needed, so it also runs on the `-thinking` variants (which serve no tool calls); for those the
prompt asks the model to reason first, and the reasoning is cut off before the report is parsed.

Same report schema, evidence check and result records as the investigating harness, so the cascade scores it
unchanged. Run on the traces a screener escalated:

python -m rosetta_flow.harness.verify --traces data/sets/refunds-dev/traces.jsonl \
    --screener-audits results/x/audits.jsonl --model swiss-ai/Apertus-v1.5-70B --out results/verify-x \
    [--limit N] [--workers 3] [--max-tokens N] [--resume]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import openai
from dotenv import find_dotenv, load_dotenv

from rosetta_flow.batch import run_batch, write_records, write_text
from rosetta_flow.harness.audit import SYSTEM_PROMPT, AuditResult, check_evidence, report_in_text
from rosetta_flow.harness.schema import AuditReport
from rosetta_flow.harness.single import full_trace
from rosetta_flow.harness.tools import as_data, dispatch
from rosetta_flow.llm import LLMConfig, LLMContext, cost_chf, redact
from rosetta_flow.trace import Trace, TraceRepo, index_by, read_jsonl

MAX_REPAIRS = 1
THINK_END = "<|inner_suffix|>"

_RULES = "Error types:" + SYSTEM_PROMPT.split("Error types:", 1)[1].replace(
    "Cite only spans you opened with read_spans (index previews are not enough). ", ""
).replace("Finish with one report call.", "")

VERIFY_PROMPT = (
    SYSTEM_PROMPT.split("Method:")[0]
    + "Method: a first-pass screener flagged this run. Check each of its findings against the whole run below and "
    "the policy. Keep a finding only if the steps it cites really show that error. If the error is real but the "
    "steps, type or quotes are wrong, correct them. Drop a finding when the agent did nothing wrong there. If no "
    "finding survives, the verdict is ok. Ignore style and tone.\n\n" + _RULES
)

AUDIT_PROMPT = (  # the screener produced no report: the confirmer reads the whole run itself
    SYSTEM_PROMPT.split("Method:")[0]
    + "Method: read the whole run below and check every claim and action against the tool results and the policy. "
    "Ignore style and tone.\n\n" + _RULES
)


def thinks(model: str) -> bool:
    return model.endswith("-thinking")


def _answer_rule(model: str) -> str:
    # The thinking variants reason only when asked to; asking for JSON only switches the reasoning off.
    if thinks(model):
        return "Think it through step by step first, then end your answer with the report JSON object."
    return "Answer with the report JSON object only."


def _findings_text(report: AuditReport | None, fence: str) -> str:
    if report is None or not report.findings:
        return "The screener could not finish its audit: audit the whole run yourself."
    rows = [{"finding": i, "error_type": f.error_type.value, "span_ids": f.span_ids, "evidence": f.evidence,
             "explanation": f.explanation} for i, f in enumerate(report.findings)]  # fmt: skip
    # The screener's words come from reading untrusted trace text, so they are fenced like the trace itself.
    return "The screener's findings to check:\n" + as_data(json.dumps(rows, ensure_ascii=False, indent=1), fence)


def final_answer(text: str) -> str:
    """The text after the model's reasoning: a thinking model's notes may quote JSON that is not its answer."""
    return text.rsplit(THINK_END, 1)[-1]


def verify(trace: Trace, policy: str, ctx: LLMContext, screened: AuditReport | None) -> AuditResult:
    repo = TraceRepo(trace, policy)
    model = ctx.model or ctx.cfg.name
    has_findings = screened is not None and bool(screened.findings)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": VERIFY_PROMPT if has_findings else AUDIT_PROMPT},
        {
            "role": "user",
            "content": f"Policy the agent must follow:\n{repo.read_policy()}\n\n"
            f"The agent run (agent description and all spans):\n"
            f"{as_data(trace.agent.description + chr(10) + full_trace(repo), repo.fence)}\n\n"
            f"{_findings_text(screened, repo.fence)}\n\n{_answer_rule(model)}",
        },
    ]
    kw: dict[str, Any] = {"max_tokens": 6000}  # room for the reasoning
    if not thinks(model):
        kw = {"max_tokens": 2000, "response_format": {"type": "json_object"}}
    t0 = time.perf_counter()
    report, failure = None, None
    for attempt in range(MAX_REPAIRS + 1):
        try:
            text = ctx.complete(messages, temperature=0, **kw)
        except openai.BadRequestError as e:
            failure = f"bad_request: {redact(str(e))[:200]}"
            break
        messages.append({"role": "assistant", "content": text})
        candidate = report_in_text(final_answer(text))
        if candidate is None:
            failure, feedback = "no_report", "End your answer with the report JSON object."
        else:
            feedback, report = dispatch(repo, "report", json.dumps(candidate))
            if report is not None:
                failure = None
                break
            failure = "invalid_report"
        if attempt < MAX_REPAIRS:
            messages.append({"role": "user", "content": feedback})
    return AuditResult(
        trace_id=trace.trace_id,
        model=model,
        report=report,
        failure=failure,
        evidence=check_evidence(repo, report) if report else [],
        tool_calls=0,
        rounds=len([m for m in messages if m["role"] == "assistant"]),
        duration_s=round(time.perf_counter() - t0, 2),
        usage=asdict(ctx.usage),
        transcript=messages,
    )


def main(argv: list[str] | None = None) -> int:
    from rosetta_flow.harness.__main__ import policy_for
    from rosetta_flow.pipeline import escalates

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--traces", type=Path, required=True)
    p.add_argument("--screener-audits", type=Path, required=True, help="the screener's audits.jsonl")
    p.add_argument("--model", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--policy-file", type=Path, default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--max-tokens", type=int, default=2_000_000, help="token budget of this invocation")
    p.add_argument("--resume", action="store_true")
    args = p.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(find_dotenv(usecwd=True))
    llm = LLMConfig.from_env()
    rows = (json.loads(x) for x in args.screener_audits.read_text(encoding="utf-8").splitlines() if x.strip())
    screened = {r["trace_id"]: AuditResult.from_record(r | {"transcript": []}) for r in rows}
    traces = [t for t in read_jsonl(args.traces, Trace) if escalates(screened.get(t.trace_id))][: args.limit]
    by_id = index_by(traces, lambda t: t.trace_id, args.traces)
    print(f"verify: {len(traces)} escalated traces with {args.model} -> {args.out}")

    def one(tid: str) -> AuditResult:
        s = screened.get(tid)
        return verify(by_id[tid], policy_for(by_id[tid], args.policy_file), LLMContext(llm, args.model),
                      s.report if s else None)  # fmt: skip

    def tokens(rec: dict[str, Any]) -> int:
        return rec["usage"].get("prompt_tokens", 0) + rec["usage"].get("completion_tokens", 0)

    outcome = run_batch(
        list(by_id), one, args.out / "progress.jsonl", to_record=AuditResult.to_record,
        key_of=lambda rec: rec["trace_id"], resume=args.resume, workers=args.workers,
        on_done=lambda tid, rec: print(f"  {tid}  {(rec['report'] or {}).get('verdict', rec['failure'])}"),
        tokens_of=tokens, max_tokens=args.max_tokens,
    )  # fmt: skip
    results = [AuditResult.from_record(outcome.done[t]) for t in by_id if t in outcome.done]
    write_records(args.out / "audits.jsonl", (r.to_record() for r in results))
    used = sum(r.usage.get("prompt_tokens", 0) + r.usage.get("completion_tokens", 0) for r in results)
    summary = {"model": args.model, "audited": len(results), "failures": outcome.failures,
               "stopped_by_budget": outcome.stopped_by_budget,
               "verdicts": {v: sum((r.report.verdict if r.report else "failed") == v for r in results)
                            for v in ("ok", "issues_found", "failed")},
               "tokens": used, "completion_tokens": sum(r.usage.get("completion_tokens", 0) for r in results),
               "cost_chf": cost_chf(args.model, used)}  # fmt: skip
    write_text(args.out / "summary.json", json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
