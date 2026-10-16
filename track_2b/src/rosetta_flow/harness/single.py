"""B0 baseline: the whole trace and the policy in one prompt, no tools, one JSON report.

Same report schema, same evidence check and same result records as the investigating harness, so the scoreboard
compares like with like. There is no grounding rule: the model sees every span in full.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from typing import Any

import openai

from rosetta_flow.harness.audit import SYSTEM_PROMPT, AuditResult, check_evidence, report_in_text
from rosetta_flow.harness.tools import as_data, dispatch
from rosetta_flow.llm import LLMContext, redact
from rosetta_flow.trace import Trace, TraceRepo

MAX_REPAIRS = 1

# The investigating prompt without its tool instructions: B0 differs from B1 only in how the trace is seen.
SINGLE_PROMPT = (
    SYSTEM_PROMPT.split("Method:")[0]
    + "Method: read the whole trace below and check every claim and action against the tool results and the "
    "policy. Ignore style and tone.\n\n"
    + ("Error types:" + SYSTEM_PROMPT.split("Error types:", 1)[1])
    .replace("Cite only spans you opened with read_spans (index previews are not enough). ", "")
    .replace("Finish with one report call.", "Answer with the report JSON only.")
)


def full_trace(repo: TraceRepo) -> str:
    t = repo.trace
    spans = "\n\n".join(repo.read_span(s.id) for s in t.spans)
    return f"trace {t.trace_id} ({t.domain}, {t.language}), {len(t.spans)} spans\n\n{spans}"


def audit_single(trace: Trace, policy: str, ctx: LLMContext) -> AuditResult:
    repo = TraceRepo(trace, policy)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SINGLE_PROMPT},
        {
            "role": "user",
            "content": f"Policy the agent must follow:\n{repo.read_policy()}\n\n"
            f"Audit this agent run (agent description and all spans):\n"
            f"{as_data(trace.agent.description + chr(10) + full_trace(repo), repo.fence)}",
        },
    ]
    t0 = time.perf_counter()
    report, failure = None, None
    for attempt in range(MAX_REPAIRS + 1):
        try:
            text = ctx.complete(messages, temperature=0, max_tokens=2000, response_format={"type": "json_object"})
        except openai.BadRequestError as e:
            failure = f"bad_request: {redact(str(e))[:200]}"
            break
        messages.append({"role": "assistant", "content": text})
        candidate = report_in_text(text)
        if candidate is None:
            failure, feedback = "no_report", "Answer with the report JSON object only."
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
        model=ctx.model or ctx.cfg.name,
        report=report,
        failure=failure,
        evidence=check_evidence(repo, report) if report else [],
        tool_calls=0,
        rounds=len([m for m in messages if m["role"] == "assistant"]),
        duration_s=round(time.perf_counter() - t0, 2),
        usage=asdict(ctx.usage),
        transcript=messages,
    )
