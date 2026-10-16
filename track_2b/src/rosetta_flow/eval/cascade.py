"""Two-tier audit, computed from existing audit runs: the screener (8B) audits every trace, the confirmer (70B)
re-audits only what the screener flagged or failed on, and its verdict is final. Traces the screener calls "ok" stay
"ok" and never reach the confirmer.

python -m rosetta_flow.eval.cascade --set data/sets/refunds-test --screener "8B=results/a/audits.jsonl"
    --confirmer "70B=results/b/audits.jsonl" [--also "B1=results/c/audits.jsonl" ...] [--out results/cascade-x]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rosetta_flow.batch import write_text
from rosetta_flow.eval.metrics import markdown_table, recall_by_type_table, score
from rosetta_flow.harness.audit import AuditResult
from rosetta_flow.pipeline import combine as pipeline_combine
from rosetta_flow.pipeline import escalates
from rosetta_flow.trace import Label, Trace, index_by, read_jsonl


def combine(screen: AuditResult | None, confirm: AuditResult | None) -> AuditResult | None:
    """The two-tier outcome for one trace, as the pipeline would produce it from these two audits."""
    return screen if not escalates(screen) else pipeline_combine(screen, confirm)


def _load(path: str) -> dict[str, AuditResult]:
    with Path(path).open(encoding="utf-8") as f:
        results = (AuditResult.from_record(json.loads(line)) for line in f if line.strip())
        return index_by(results, lambda r: r.trace_id, path)


def _tokens(r: AuditResult | None) -> int:
    return 0 if r is None else r.usage.get("prompt_tokens", 0) + r.usage.get("completion_tokens", 0)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--set", type=Path, required=True)
    p.add_argument("--screener", required=True, help="NAME=audits.jsonl of the small model")
    p.add_argument("--confirmer", required=True, help="NAME=audits.jsonl of the large model")
    p.add_argument("--also", nargs="*", default=[], help="more NAME=audits.jsonl systems for the same table")
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8")
    traces = index_by(read_jsonl(args.set / "traces.jsonl", Trace), lambda t: t.trace_id, args.set)
    labels = index_by(read_jsonl(args.set / "labels.jsonl", Label), lambda lb: lb.trace_id, args.set)
    s_name, _, s_path = args.screener.partition("=")
    c_name, _, c_path = args.confirmer.partition("=")
    screen, confirm = _load(s_path), _load(c_path)
    tiered = {tid: r for tid in labels if (r := combine(screen.get(tid), confirm.get(tid))) is not None}
    name = f"{s_name} screens, {c_name} confirms"

    also = (a.partition("=") for a in args.also)
    summaries = [score(n, traces, labels, _load(path)).summary() for n, _, path in also]
    summaries += [score(s_name, traces, labels, screen).summary(), score(c_name, traces, labels, confirm).summary(),
                  score(name, traces, labels, tiered).summary()]  # fmt: skip
    escalated = [tid for tid in labels if escalates(screen.get(tid))]
    confirm_all = sum(_tokens(confirm.get(t)) for t in labels)
    confirm_used = sum(_tokens(confirm.get(t)) for t in escalated)
    tiers: dict[str, Any] = {
        "traces": len(labels),
        "escalated_to_confirmer": len(escalated),
        "escalated_share": round(len(escalated) / max(1, len(labels)), 3),
        "confirmer_tokens_used": confirm_used,
        "confirmer_tokens_if_alone": confirm_all,
        "confirmer_token_share": round(confirm_used / max(1, confirm_all), 3),
        "screener_tokens": sum(_tokens(screen.get(t)) for t in labels),
    }
    table = markdown_table(summaries) + "\n\nRecall by error type (found and pointed at the right step):\n\n"
    table += recall_by_type_table(summaries)
    table += (f"\n\nTwo tiers: {tiers['escalated_to_confirmer']} of {tiers['traces']} traces "
              f"({tiers['escalated_share']:.0%}) reach the confirmer, which then spends "
              f"{tiers['confirmer_token_share']:.0%} of the tokens it would need alone.\n")  # fmt: skip
    out = args.out or Path("results") / f"cascade-{datetime.now(UTC):%Y%m%d-%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    meta = {"created": datetime.now(UTC).isoformat(timespec="seconds"), "set": str(args.set), "tiers": tiers,
            "systems": summaries}  # fmt: skip
    write_text(out / "metrics.json", json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    write_text(out / "table.md", table)
    print(table)
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
