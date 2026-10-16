"""Demo data for the web app: dev traces with their labels and precomputed reference-auditor (70B) audits.

The app shows these without any API call; live audits are on demand. Transcripts are dropped (they are the
bulk of the size and the page does not show them).

python -m rosetta_flow.app.demo --set data/sets/refunds-dev --audits results/v9-refunds-70B-a/audits.jsonl \
    --set data/sets/manufacturing-dev --audits results/v9-manufacturing-70B-a/audits.jsonl --out data/demo
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from rosetta_flow.batch import write_text
from rosetta_flow.harness.audit import AuditResult

# Relative to the working directory: track_2b locally, /app in the Docker image (both hold data/demo).
DEMO_DIR = Path(os.environ.get("ROSETTA_DEMO_DIR", "data/demo"))


def build(sets: list[Path], audits: list[Path], out: Path) -> dict[str, int]:
    if len(sets) != len(audits):
        raise SystemExit("give one --audits file per --set")
    traces, labels, reports = [], [], []
    for set_dir, audit_file in zip(sets, audits, strict=True):
        traces += (set_dir / "traces.jsonl").read_text(encoding="utf-8").splitlines()
        labels += (set_dir / "labels.jsonl").read_text(encoding="utf-8").splitlines()
        for line in audit_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                rec.pop("transcript", None)
                reports.append(json.dumps(rec, ensure_ascii=False))
    out.mkdir(parents=True, exist_ok=True)
    for name, lines in (("traces", traces), ("labels", labels), ("audits", reports)):
        write_text(out / f"{name}.jsonl", "\n".join(x for x in lines if x.strip()) + "\n")
    return {"traces": len(traces), "labels": len(labels), "audits": len(reports)}


def build_fleet(sets: list[Path], screener: list[Path], confirmer: list[Path], out: Path) -> dict[str, int]:
    """The measured two-tier test results, one compact row per run, for the fleet replay (no model calls)."""
    from rosetta_flow.pipeline import escalates
    from rosetta_flow.trace import Label

    def audits(path: Path) -> dict[str, AuditResult]:
        rows = (json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip())
        return {r["trace_id"]: AuditResult.from_record(r | {"transcript": []}) for r in rows}

    def tokens(r: AuditResult | None) -> int:
        return 0 if r is None else r.usage.get("prompt_tokens", 0) + r.usage.get("completion_tokens", 0)

    rows = []
    for set_dir, s_path, c_path in zip(sets, screener, confirmer, strict=True):
        screen, confirm = audits(s_path), audits(c_path)
        for line in (set_dir / "labels.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            label = Label.model_validate_json(line)
            s, c = screen.get(label.trace_id), confirm.get(label.trace_id)
            up = escalates(s)
            final = c if up else s
            verdict = final.report.verdict if final and final.report else "failed"
            rows.append({"id": label.trace_id, "domain": label.trace_id.split("-")[0],
                         "error": label.errors[0].type.value if label.errors else None,
                         "screen": s.report.verdict if s and s.report else "failed", "escalated": up,
                         "final": verdict, "tok8": tokens(s), "tok70": tokens(c) if up else 0,
                         "tok70_alone": tokens(c),
                         "alone": c.report.verdict if c and c.report else "failed"})  # fmt: skip
    write_text(out / "fleet.json", json.dumps({"runs": rows}, ensure_ascii=False) + "\n")
    return {"fleet_runs": len(rows)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--set", type=Path, action="append", required=True, dest="sets")
    p.add_argument("--audits", type=Path, action="append", required=True)
    p.add_argument("--out", type=Path, default=DEMO_DIR)
    args = p.parse_args(argv)
    print(json.dumps(build(args.sets, args.audits, args.out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
