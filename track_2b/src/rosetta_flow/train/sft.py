"""Turn kept gold investigations into SFT examples: clean tool-call conversations the on-prem 8B imitates.

A raw transcript also holds the harness's corrections (rejected reports, "open the spans you cite", nudges) and
repeated reads. Imitating those would teach the detours, so each example is rebuilt as the clean path: the
reference auditor's own investigation steps in order, each span read once, every cited span opened before the
report, and one final report call with the accepted report.

python -m rosetta_flow.train.sft --gold data/gold/refunds-train data/gold/manufacturing-train --sets
    data/sets/refunds-train data/sets/manufacturing-train --out data/sft/train.jsonl [--balance]
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from rosetta_flow.batch import write_records, write_text
from rosetta_flow.harness.__main__ import policy_for
from rosetta_flow.harness.audit import AuditResult
from rosetta_flow.harness.tools import AUDITOR_TOOLS, parse_arguments, read_spans_text, requested_span_ids
from rosetta_flow.llm import strip_markup
from rosetta_flow.trace import Trace, TraceRepo, index_by, normalize_span_id, read_jsonl

INVESTIGATION_TOOLS = {"read_spans", "read_span", "search", "list_spans"}
MAX_THOUGHT_CHARS = 600  # the 70B's analysis notes are long; the 8B learns the moves, with a short rationale
# Without the check that precedes the report, the 8B learned to report but not to compare (v2 on test: right type,
# wrong steps, more false alarms), so --analysis keeps it, capped near the 90th percentile of its length.
MAX_ANALYSIS_CHARS = 3500
_FENCE_TAG = re.compile(r"<<<data ([0-9a-f]{6}) from the audited run")


def build_example(record: dict[str, Any], trace: Trace, policy: str, analysis: bool = False) -> dict[str, Any]:
    result = AuditResult.from_record(record)
    assert result.report is not None, "only kept investigations become examples"
    transcript = result.transcript
    repo = TraceRepo(trace, policy)
    # Tool outputs already in the transcript carry the audit's fence tag; inserted reads must use the same one.
    if tag := next((m.group(1) for msg in transcript if (m := _FENCE_TAG.search(str(msg.get("content"))))), None):
        repo.fence = tag

    messages: list[dict[str, Any]] = [transcript[0], transcript[1]]  # system prompt, task with policy and index
    outputs = {m["tool_call_id"]: m["content"] for m in transcript if m["role"] == "tool"}
    opened: set[str] = set()
    n = 0

    def add_call(thought: str, name: str, arguments: dict[str, Any], output: str) -> None:
        nonlocal n
        call_id = f"call_{n}"
        n += 1
        messages.append({
            "role": "assistant",
            "content": thought,
            "tool_calls": [{"id": call_id, "type": "function",
                            "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}],
        })  # fmt: skip
        messages.append({"role": "tool", "tool_call_id": call_id, "content": output})

    for msg in transcript[2:]:
        if msg["role"] != "assistant" or not msg.get("tool_calls"):
            continue  # harness notes, nudges, rejections, free-text turns
        thought = _thought(msg.get("content"))
        for tc in msg["tool_calls"]:
            name, raw = tc["function"]["name"], tc["function"]["arguments"]
            if name not in INVESTIGATION_TOOLS or tc["id"] not in outputs:
                continue
            args = parse_arguments(name, raw)
            if not isinstance(args, dict):
                continue
            if name in ("read_spans", "read_span"):
                fresh = [sid for sid in _ids(requested_span_ids(args)) if sid not in opened]
                if not fresh:
                    continue  # a re-read adds nothing the model has not seen
                opened.update(fresh)
                add_call(thought, "read_spans", {"span_ids": fresh}, read_spans_text(repo, fresh))
            else:
                add_call(thought, name, args, outputs[tc["id"]])
            thought = ""  # the rationale belongs to the first call of the turn

    cited = sorted({sid for f in result.report.findings for sid in f.span_ids} - opened)
    if cited:  # spans the harness handed over: in the clean path the model opens them itself
        add_call("", "read_spans", {"span_ids": cited}, read_spans_text(repo, cited))
    report = result.report.model_dump(mode="json", exclude_none=True)
    report["findings"] = [{k: v for k, v in f.items() if k != "type_as_written"} for f in report["findings"]]
    messages.append({
        "role": "assistant",
        "content": _analysis(transcript) if analysis else "",
        "tool_calls": [{"id": f"call_{n}", "type": "function",
                        "function": {"name": "report", "arguments": json.dumps(report, ensure_ascii=False)}}],
    })  # fmt: skip
    return {"messages": messages, "tools": AUDITOR_TOOLS, "trace_id": trace.trace_id, "verdict": report["verdict"]}


def _analysis(transcript: list[dict[str, Any]]) -> str:
    """The reference auditor's rule-by-rule check written alongside its report (the longest one, if it reported
    more than once: later attempts tend to be short evidence corrections). Line breaks are kept. A report written
    as JSON in the reply (no report call) keeps only the prose around the JSON."""

    def reports(m: dict[str, Any]) -> bool:
        return m["role"] == "assistant" and any(tc["function"]["name"] == "report" for tc in m.get("tool_calls") or [])

    texts = [strip_markup(m.get("content")).strip() for m in transcript if reports(m)]
    if not any(texts):
        texts = [_without_json(strip_markup(m.get("content"))) for m in transcript if m["role"] == "assistant"]
    text = max(texts, key=len, default="")
    return text if len(text) <= MAX_ANALYSIS_CHARS else text[:MAX_ANALYSIS_CHARS].rsplit("\n", 1)[0]


def _without_json(text: str) -> str:
    """Text with its first JSON object (a report written in the reply) cut out; '' if there is none."""
    start = text.find("{")
    if start < 0:
        return ""
    try:
        _, end = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError:
        return ""
    rest = (text[:start] + text[end:]).strip()
    return rest.removeprefix("Reasoning:").strip()


def _thought(content: str | None) -> str:
    text = " ".join(strip_markup(content).split())
    return text if len(text) <= MAX_THOUGHT_CHARS else text[: MAX_THOUGHT_CHARS - 3].rsplit(" ", 1)[0] + "..."


def _ids(raw: list[Any]) -> list[str]:
    out = []
    for r in raw:
        try:
            sid = normalize_span_id(r)
        except KeyError:
            continue
        if sid not in out:
            out.append(sid)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--gold", type=Path, nargs="+", required=True, help="gold folders (gold.jsonl)")
    p.add_argument("--sets", type=Path, nargs="+", required=True, help="the dataset folders the gold came from")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--max-chars", type=int, default=24_000, help="drop examples longer than this (T4 context)")
    p.add_argument("--balance", action="store_true", help="cap clean examples per domain at the error count")
    p.add_argument("--analysis", action="store_true", help="keep the rule-by-rule check before the report call")
    args = p.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8")
    traces: dict[str, Trace] = {}
    for s in args.sets:
        traces |= index_by(read_jsonl(s / "traces.jsonl", Trace), lambda t: t.trace_id, s)
    examples, skipped = [], Counter()
    for g in args.gold:
        with (g / "gold.jsonl").open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                rec = json.loads(line)
                trace = traces[rec["trace_id"]]
                ex = build_example(rec["audit"], trace, policy_for(trace, None), analysis=args.analysis)
                if len(json.dumps(ex["messages"], ensure_ascii=False)) > args.max_chars:
                    skipped["too_long"] += 1
                    continue
                examples.append(ex | {"domain": rec["domain"], "language": rec["language"]})
    if args.balance:
        # The reference auditor solves clean traces about twice as often as error traces; unbalanced, the 8B
        # would learn that most runs are fine. Clean examples are capped per domain at the number of error ones.
        rng = random.Random(0)
        balanced = []
        for domain in sorted({e["domain"] for e in examples}):
            errors = [e for e in examples if e["domain"] == domain and e["verdict"] == "issues_found"]
            clean = [e for e in examples if e["domain"] == domain and e["verdict"] == "ok"]
            balanced += errors + rng.sample(clean, min(len(clean), len(errors)))
        skipped["clean_over_balance"] = len(examples) - len(balanced)
        examples = balanced
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_records(args.out, examples)
    manifest = {
        "examples": len(examples),
        "skipped": dict(skipped),
        "by_domain": dict(Counter(e["domain"] for e in examples)),
        "by_verdict": dict(Counter(e["verdict"] for e in examples)),
        "by_language": dict(Counter(e["language"] for e in examples)),
        "tool_calls_mean": round(
            sum(sum(1 for m in e["messages"] if m.get("tool_calls")) for e in examples) / max(1, len(examples)), 1
        ),
    }
    write_text(args.out.with_suffix(".manifest.json"), json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest))
    return 0 if examples else 1


if __name__ == "__main__":
    sys.exit(main())
