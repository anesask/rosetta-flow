"""Score one or more audit runs against the labels of a dataset.

python -m rosetta_flow.eval --set data/sets/refunds-dev --audits 70B=results/a/audits.jsonl 8B=results/b/audits.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from rosetta_flow.batch import write_text
from rosetta_flow.eval.metrics import markdown_table, recall_by_type_table, score, with_min_confidence
from rosetta_flow.harness.audit import AuditResult
from rosetta_flow.trace import Label, Trace, index_by, read_jsonl


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--set", type=Path, required=True, help="dataset folder with traces.jsonl and labels.jsonl")
    p.add_argument("--audits", nargs="+", required=True, help="NAME=path/to/audits.jsonl, one per system")
    p.add_argument("--out", type=Path, default=None, help="default: results/eval-<UTC timestamp>")
    p.add_argument("--limit", type=int, default=None, help="score only the first N traces (as audited with --limit)")
    p.add_argument("--min-confidence", type=float, default=0.0, help="drop findings below this (tune on dev only)")
    args = p.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8")
    trace_list = list(read_jsonl(args.set / "traces.jsonl", Trace))[: args.limit]
    traces = index_by(trace_list, lambda t: t.trace_id, args.set / "traces.jsonl")
    labels = index_by(read_jsonl(args.set / "labels.jsonl", Label), lambda lb: lb.trace_id, args.set / "labels.jsonl")
    labels = {tid: lb for tid, lb in labels.items() if tid in traces}
    summaries = []
    for spec in args.audits:
        name, _, path = spec.partition("=")
        with Path(path).open(encoding="utf-8") as f:
            records = (AuditResult.from_record(json.loads(line)) for line in f if line.strip())
            thresholded = (with_min_confidence(r, args.min_confidence) for r in records)
            audits = index_by(thresholded, lambda r: r.trace_id, path)
        missing = set(labels) - set(audits)
        if missing:
            print(f"warning: {name} has no audit for {len(missing)} traces (counted as failed)", file=sys.stderr)
        summaries.append(score(name, traces, labels, audits).summary())

    out = args.out or Path("results") / f"eval-{datetime.now(UTC):%Y%m%d-%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    meta = {"created": datetime.now(UTC).isoformat(timespec="seconds"), "set": str(args.set), "systems": summaries}
    write_text(out / "metrics.json", json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    table = markdown_table(summaries) + "\n\nRecall by error type (found and pointed at the right step):\n\n"
    table += recall_by_type_table(summaries)
    write_text(out / "table.md", table + "\n")
    print(table)
    print(f"\n-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
