"""Runs from agents we did not write: tau-bench (Sierra, MIT licence, https://github.com/sierra-research/tau-bench).

Its historical trajectories are OpenAI-style message lists (system = the airline's or shop's policy) with an
objective outcome: reward 1 if the final database state matches the task, else 0. A failed task means the agent got
something wrong, but tau-bench does not say at which step, so these runs carry an outcome file instead of our
span-level labels, and they are scored for detection only. Evaluation only: never trained on.

python -m rosetta_flow.gen.taubench convert --input gpt-4o-airline.json --domain airline
    --out data/sets/taubench-airline
    [--n 100 --seed 0]
python -m rosetta_flow.gen.taubench score --set data/sets/taubench-airline --audits "70B=a.jsonl" "8B=b.jsonl"
    [--screener 8B=b.jsonl --confirmer 70B=a.jsonl]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

from rosetta_flow.batch import write_records, write_text
from rosetta_flow.trace import Trace

AGENTS = {"airline": "Airline customer service agent", "retail": "Online retail customer service agent"}
# MIT requires the copyright notice wherever the converted runs are redistributed (dataset manifest).
NOTICE = "tau-bench (github.com/sierra-research/tau-bench), MIT License, Copyright (c) 2024 Sierra; eval only."


def _parse(text: str | None) -> Any:
    try:
        return json.loads(text or "")
    except json.JSONDecodeError:
        return text or ""


def convert_run(run: dict[str, Any], domain: str, source: str) -> tuple[Trace, str]:
    """One tau-bench run as our trace, plus its policy (the system message)."""
    messages = run["traj"]
    policy = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
    spans: list[dict[str, Any]] = []

    def add(**fields: Any) -> None:
        spans.append({"id": f"{len(spans):03d}", **fields})

    for m in messages[1:]:
        content = (m.get("content") or "").strip()
        if m["role"] == "user" and content:
            add(kind="user_message", text=content)
        elif m["role"] == "assistant":
            calls = m.get("tool_calls") or []
            if content:
                add(kind="llm_reasoning" if calls else "agent_message", text=content)
            for tc in calls:
                fn = tc["function"]
                args = _parse(fn.get("arguments"))
                add(kind="tool_call", tool=fn["name"], args=args if isinstance(args, dict) else {"raw": args},
                    call_id=tc["id"])  # fmt: skip
        elif m["role"] == "tool":
            result = _parse(m.get("content"))
            failed = isinstance(result, str) and result.lower().startswith("error")
            add(kind="tool_result", call_id=m["tool_call_id"], status="error" if failed else "ok", result=result)
    trace_id = f"tau-{domain}-{source}-t{run['task_id']:03d}-r{run.get('trial', 0)}"
    trace = Trace.model_validate({
        "trace_id": trace_id, "domain": domain, "language": "en", "policy_id": f"tau-{domain}",
        "agent": {"name": f"tau-bench {source}", "description": AGENTS[domain]}, "spans": spans,
    })  # fmt: skip
    return trace, policy


def convert(input_path: Path, domain: str, out: Path, n: int, seed: int) -> dict[str, Any]:
    runs = json.loads(input_path.read_text(encoding="utf-8"))
    source = input_path.stem.removesuffix(f"-{domain}")
    rng = random.Random(seed)
    passed = [r for r in runs if r["reward"] == 1]
    failed = [r for r in runs if r["reward"] != 1]
    take = n // 2  # balanced, so detection is not dominated by the base rate
    chosen = rng.sample(passed, min(take, len(passed))) + rng.sample(failed, min(n - take, len(failed)))
    traces, outcomes, policies = [], [], set()
    for run in chosen:
        trace, policy = convert_run(run, domain, source)
        traces.append(trace)
        policies.add(policy)
        outcomes.append({"trace_id": trace.trace_id, "task_failed": run["reward"] != 1, "reward": run["reward"]})
    if len(policies) != 1:
        raise SystemExit(f"expected one policy for {domain}, found {len(policies)}")
    out.mkdir(parents=True, exist_ok=True)
    write_records(out / "traces.jsonl", (t.model_dump(mode="json", exclude_none=True) for t in traces))
    write_records(out / "outcomes.jsonl", outcomes)
    write_text(out / "policy.md", policies.pop() + "\n")
    manifest = {"source": str(input_path.name), "notice": NOTICE, "domain": domain, "seed": seed, "traces": len(traces),
                "task_failed": sum(o["task_failed"] for o in outcomes),
                "spans_mean": round(sum(len(t.spans) for t in traces) / max(1, len(traces)), 1)}  # fmt: skip
    write_text(out / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    return manifest


def detection(flags: dict[str, bool | None], outcomes: dict[str, bool]) -> dict[str, float]:
    """Flag = the auditor reported issues; None = no usable audit, counted as wrong either way."""
    pos = [t for t, failed in outcomes.items() if failed]
    neg = [t for t, failed in outcomes.items() if not failed]
    tpr = sum(flags.get(t) is True for t in pos) / max(1, len(pos))
    tnr = sum(flags.get(t) is False for t in neg) / max(1, len(neg))
    return {"balanced_acc": round((tpr + tnr) / 2, 3), "recall": round(tpr, 3), "false_alarms": round(1 - tnr, 3),
            "failed_audits": sum(flags.get(t) is None for t in outcomes)}  # fmt: skip


def _flags(path: str) -> dict[str, Any]:
    out = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out[r["trace_id"]] = r
    return out


def _verdict(rec: dict[str, Any] | None) -> bool | None:
    rep = (rec or {}).get("report")
    return None if rep is None else rep["verdict"] == "issues_found"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("convert")
    c.add_argument("--input", type=Path, required=True)
    c.add_argument("--domain", choices=sorted(AGENTS), required=True)
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--n", type=int, default=100)
    c.add_argument("--seed", type=int, default=0)
    s = sub.add_parser("score")
    s.add_argument("--set", type=Path, required=True)
    s.add_argument("--audits", nargs="*", default=[], help="NAME=audits.jsonl")
    s.add_argument("--screener", default=None, help="NAME=audits.jsonl of the small model, for the two tiers")
    s.add_argument("--confirmer", default=None, help="NAME=audits.jsonl of the large model, for the two tiers")
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    if args.cmd == "convert":
        print(json.dumps(convert(args.input, args.domain, args.out, args.n, args.seed)))
        return 0
    outcomes = {o["trace_id"]: o["task_failed"] for o in (json.loads(x) for x in
                (args.set / "outcomes.jsonl").read_text(encoding="utf-8").splitlines() if x.strip())}  # fmt: skip
    rows = {}
    for spec in args.audits:
        name, _, path = spec.partition("=")
        recs = _flags(path)
        rows[name] = detection({t: _verdict(recs.get(t)) for t in outcomes}, outcomes)
    if args.screener and args.confirmer:
        s_name, _, s_path = args.screener.partition("=")
        c_name, _, c_path = args.confirmer.partition("=")
        screen, confirm = _flags(s_path), _flags(c_path)
        two = {t: (_verdict(confirm.get(t)) if _verdict(screen.get(t)) is not False else False) for t in outcomes}
        up = sum(_verdict(screen.get(t)) is not False for t in outcomes)
        rows[f"{s_name} screens, {c_name} confirms"] = detection(two, outcomes) | {
            "escalated": round(up / len(outcomes), 3)
        }
    print(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
