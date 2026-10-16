"""The two-tier audit pipeline as configurable components: a screener (small model) audits every run, an escalation
rule picks the runs a confirmer (large model) re-audits, and optional parts switch on per deployment: screener
bookmarks, their handoff to the confirmer, and human review (see rosetta_flow.review).

python -m rosetta_flow.pipeline --traces data/sets/refunds-dev/traces.jsonl --config pipeline.toml
    --out results/pipeline-x [--policy-file policy.md] [--limit N] [--workers 3] [--max-tokens N] [--resume]
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import find_dotenv, load_dotenv

from rosetta_flow.batch import run_batch, write_records, write_text
from rosetta_flow.harness.audit import AuditResult, HarnessOptions, audit
from rosetta_flow.llm import LLMConfig, LLMContext, cost_chf
from rosetta_flow.trace import Trace, index_by, read_jsonl

ESCALATION_RULES = ("flagged", "failed")
TIER_MODES = ("audit", "verify")


@dataclass(frozen=True)
class Tier:
    model: str
    base_url: str | None = None  # on-prem the tiers usually run on different servers; None = LLM_BASE_URL
    # Confirmer only: "audit" investigates the run again with tools; "verify" checks the screener's findings in one
    # prompt (no tools, so it also runs on the -thinking variants; rosetta_flow.harness.verify).
    mode: str = "audit"

    def __post_init__(self) -> None:
        if self.mode not in TIER_MODES:
            raise ValueError(f"unknown tier mode {self.mode!r}; use {list(TIER_MODES)}")


@dataclass(frozen=True)
class PipelineConfig:
    screener: Tier
    confirmer: Tier | None = None  # None: the screener's verdict is final
    escalate_on: frozenset[str] = frozenset(ESCALATION_RULES)
    bookmarks: bool = False  # the screener may bookmark suspicious spans
    handoff: bool = False  # the confirmer starts from the screener's bookmarks (needs bookmarks)
    review: bool = False  # findings wait for a human decision (rosetta_flow.review)
    screener_max_tokens: int | None = 40_000  # a screener that loops fails fast and escalates instead

    def __post_init__(self) -> None:
        if unknown := self.escalate_on - set(ESCALATION_RULES):
            raise ValueError(f"unknown escalation rules {sorted(unknown)}; use {list(ESCALATION_RULES)}")
        if self.handoff and not self.bookmarks:
            raise ValueError("handoff needs bookmarks = true")

    @classmethod
    def from_toml(cls, path: Path) -> PipelineConfig:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        tiers = {k: Tier(**raw[k]) for k in ("screener", "confirmer") if k in raw}
        options = raw.get("options", {})
        return cls(
            screener=tiers["screener"],
            confirmer=tiers.get("confirmer"),
            escalate_on=frozenset(options.get("escalate_on", ESCALATION_RULES)),
            bookmarks=bool(options.get("bookmarks", False)),
            handoff=bool(options.get("handoff", False)),
            review=bool(options.get("review", False)),
            screener_max_tokens=options.get("screener_max_tokens", 40_000) or None,
        )


def escalates(result: AuditResult | None, rules: frozenset[str] = frozenset(ESCALATION_RULES)) -> bool:
    """Whether the screener hands a run on: it flagged it, or it produced no usable report."""
    if result is None or result.report is None:
        return "failed" in rules
    return "flagged" in rules and result.report.verdict == "issues_found"


def combine(screen: AuditResult | None, confirm: AuditResult | None) -> AuditResult | None:
    """The final outcome for one run: the confirmer's audit when there is one, else the screener's. Time and tokens
    of both tiers are added up, so the result scores like any single audit."""
    if confirm is None or screen is None:
        return confirm or screen
    usage = {k: screen.usage.get(k, 0) + confirm.usage.get(k, 0) for k in ("prompt_tokens", "completion_tokens")}
    return replace(confirm, duration_s=screen.duration_s + confirm.duration_s, usage=usage,
                   tool_calls=screen.tool_calls + confirm.tool_calls)  # fmt: skip


@dataclass
class PipelineResult:
    trace_id: str
    screen: AuditResult
    confirm: AuditResult | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def escalated(self) -> bool:
        return self.confirm is not None

    @property
    def final(self) -> AuditResult:
        result = combine(self.screen, self.confirm)
        assert result is not None
        return result

    def to_record(self) -> dict[str, Any]:
        return {"trace_id": self.trace_id, "screen": self.screen.to_record(),
                "confirm": self.confirm.to_record() if self.confirm else None, "meta": self.meta}  # fmt: skip

    @classmethod
    def from_record(cls, rec: dict[str, Any]) -> PipelineResult:
        confirm = AuditResult.from_record(rec["confirm"]) if rec.get("confirm") else None
        return cls(rec["trace_id"], AuditResult.from_record(rec["screen"]), confirm, rec.get("meta", {}))


def _context(llm: LLMConfig, tier: Tier) -> LLMContext:
    cfg = replace(llm, base_url=tier.base_url.rstrip("/")) if tier.base_url else llm
    return LLMContext(cfg, tier.model)


def confirm(trace: Trace, policy: str, config: PipelineConfig, llm: LLMConfig, screen: AuditResult,
            hints: list[dict[str, str]] | None = None) -> AuditResult:  # fmt: skip
    """The confirmer's audit of an escalated run, in the mode its tier is set to."""
    from rosetta_flow.harness.verify import verify

    assert config.confirmer is not None
    ctx = _context(llm, config.confirmer)
    if config.confirmer.mode == "verify":
        return verify(trace, policy, ctx, screen.report)
    return audit(trace, policy, ctx, hints=hints)


def run(trace: Trace, policy: str, config: PipelineConfig, llm: LLMConfig) -> PipelineResult:
    screen = audit(
        trace,
        policy,
        _context(llm, config.screener),
        options=HarnessOptions(bookmarks=config.bookmarks),
        max_tokens=config.screener_max_tokens,
    )
    result = PipelineResult(trace.trace_id, screen, meta={"bookmarks": len(screen.bookmarks)})
    if config.confirmer is not None and escalates(screen, config.escalate_on):
        hints = screen.bookmarks if config.handoff else None
        result.confirm = confirm(trace, policy, config, llm, screen, hints)
        result.meta["handoff"] = bool(hints)
    return result


def _tokens(r: AuditResult | None) -> int:
    return 0 if r is None else r.usage.get("prompt_tokens", 0) + r.usage.get("completion_tokens", 0)


def main(argv: list[str] | None = None) -> int:
    from rosetta_flow.harness.__main__ import policy_for

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--traces", type=Path, required=True)
    p.add_argument("--config", type=Path, default=Path("pipeline.toml"))
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--policy-file", type=Path, default=None, help="your agent's policy (runs outside our domains)")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--max-tokens", type=int, default=5_000_000, help="token budget of this invocation")
    p.add_argument("--resume", action="store_true")
    args = p.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(find_dotenv(usecwd=True))
    config, llm = PipelineConfig.from_toml(args.config), LLMConfig.from_env()
    traces = list(read_jsonl(args.traces, Trace))[: args.limit]
    by_id = index_by(traces, lambda t: t.trace_id, args.traces)
    policies = {t.trace_id: policy_for(t, args.policy_file) for t in traces}
    print(f"pipeline on {len(traces)} traces: {config} -> {args.out}")

    def describe(rec: dict[str, Any]) -> str:
        r = PipelineResult.from_record(rec)
        verdict = r.final.report.verdict if r.final.report else f"failed ({r.final.failure})"
        return f"{'screener -> confirmer' if r.escalated else 'screener'}: {verdict}"

    outcome = run_batch(
        list(by_id),
        lambda tid: run(by_id[tid], policies[tid], config, llm),
        args.out / "progress.jsonl",
        to_record=PipelineResult.to_record,
        key_of=lambda rec: rec["trace_id"],
        resume=args.resume,
        workers=args.workers,
        on_done=lambda tid, rec: print(f"  {tid}  {describe(rec)}"),
        tokens_of=lambda rec: sum(_tokens(AuditResult.from_record(a)) for a in (rec["screen"], rec["confirm"]) if a),
        max_tokens=args.max_tokens,
    )
    results = [PipelineResult.from_record(outcome.done[t]) for t in by_id if t in outcome.done]
    write_records(args.out / "pipeline.jsonl", (r.to_record() for r in results))
    write_records(args.out / "audits.jsonl", (r.final.to_record() for r in results))  # scoreable by eval
    screen_tokens = sum(_tokens(r.screen) for r in results)
    confirm_tokens = sum(_tokens(r.confirm) for r in results)
    chf = [cost_chf(config.screener.model, screen_tokens)]
    if config.confirmer:
        chf.append(cost_chf(config.confirmer.model, confirm_tokens))
    used = {
        "screener": config.screener.model,
        "confirmer": config.confirmer.model if config.confirmer else None,
        "confirmer_mode": config.confirmer.mode if config.confirmer else None,
        "escalate_on": sorted(config.escalate_on),
        "bookmarks": config.bookmarks,
        "handoff": config.handoff,
        "review": config.review,
    }
    summary = {
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "traces_file": str(args.traces),
        "config": used,
        "audited": len(results),
        "failures": outcome.failures,
        "stopped_by_budget": outcome.stopped_by_budget,
        "escalated": sum(r.escalated for r in results),
        "verdicts": dict(Counter(r.final.report.verdict if r.final.report else "failed" for r in results)),
        "bookmarks_mean": round(sum(len(r.screen.bookmarks) for r in results) / max(1, len(results)), 2),
        "tokens": {"screener": screen_tokens, "confirmer": confirm_tokens},
        "cost_chf": round(sum(c for c in chf if c is not None), 4) if all(c is not None for c in chf) else None,
    }
    write_text(args.out / "summary.json", json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("created", "traces_file")}, ensure_ascii=False))
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
