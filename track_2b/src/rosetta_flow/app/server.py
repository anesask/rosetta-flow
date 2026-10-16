"""Web app: browse audited agent runs, see findings on the exact steps, audit a run live, and break an agent
(sabotage a recorded run, watch the two tiers catch it: rosetta_flow.app.live).

Runs from data/demo come with precomputed audits, so the page works without an API call. A live audit uses the
model from LLM_NAME / LLM_BASE_URL / LLM_API_KEY, one at a time.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from rosetta_flow.app import live
from rosetta_flow.app.demo import DEMO_DIR
from rosetta_flow.harness.__main__ import policy_for
from rosetta_flow.harness.audit import AuditResult, audit
from rosetta_flow.llm import LLMConfig, LLMContext, redact
from rosetta_flow.pipeline import PipelineConfig, Tier
from rosetta_flow.review import ReviewLog
from rosetta_flow.trace import Label, Trace, read_jsonl

STATIC = Path(__file__).parent / "static"
SEVERITY = {"low": 1, "medium": 2, "high": 3}


class Store:
    def __init__(self, demo_dir: Path) -> None:
        self.traces = {t.trace_id: t for t in read_jsonl(demo_dir / "traces.jsonl", Trace)}
        self.labels = {lb.trace_id: lb for lb in read_jsonl(demo_dir / "labels.jsonl", Label)}
        self.audits: dict[str, AuditResult] = {}
        with (demo_dir / "audits.jsonl").open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    rec.setdefault("transcript", [])
                    self.audits[rec["trace_id"]] = AuditResult.from_record(rec)
        self.live: set[str] = set()


def _summary(store: Store, trace: Trace) -> dict[str, Any]:
    result = store.audits.get(trace.trace_id)
    report = result.report if result else None
    label = store.labels.get(trace.trace_id)
    findings = report.findings if report else []
    return {
        "trace_id": trace.trace_id,
        "domain": trace.domain,
        "language": trace.language,
        "steps": len(trace.spans),
        "verdict": report.verdict if report else ("failed" if result else "not_audited"),
        "findings": len(findings),
        "severity": max((f.severity for f in findings), key=lambda s: SEVERITY.get(s, 0), default=None),
        "types": sorted({f.error_type.value for f in findings}),
        "truth": [e.type.value for e in label.errors] if label else None,
        "live": trace.trace_id in store.live,
    }


def _detail(store: Store, trace: Trace) -> dict[str, Any]:
    result = store.audits.get(trace.trace_id)
    label = store.labels.get(trace.trace_id)
    return {
        "summary": _summary(store, trace),
        "agent": trace.agent.model_dump(),
        "spans": [s.model_dump(mode="json", exclude_none=True) for s in trace.spans],
        "audit": None
        if result is None
        else {
            "model": result.model,
            "failure": result.failure,
            "report": result.report.model_dump(mode="json") if result.report else None,
            "evidence": [vars(e) for e in result.evidence],
            "tool_calls": result.tool_calls,
            "duration_s": result.duration_s,
            "spans_read": result.spans_read,
        },
        "truth": None if label is None else [{"type": e.type.value, "span_ids": e.span_ids} for e in label.errors],
    }


class ReviewIn(BaseModel):
    trace_id: str
    finding: int
    decision: str
    reviewer: str
    note: str = ""


def create_app(demo_dir: Path = DEMO_DIR, cfg: LLMConfig | None = None, review_log: Path | None = None) -> FastAPI:
    store = Store(demo_dir)
    reviews = ReviewLog(review_log or Path(os.environ.get("ROSETTA_REVIEW_LOG", "reviews/review_log.jsonl")))
    app = FastAPI(title="rosetta-flow", docs_url=None, redoc_url=None)
    one_live_audit = threading.Lock()  # keeps API usage to one audit at a time

    def trace_or_404(trace_id: str) -> Trace:
        if trace_id not in store.traces:
            raise HTTPException(404, "unknown run")
        return store.traces[trace_id]

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    # The React bundle (built from web/ with `npm run build`, committed under static/assets)
    if (STATIC / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/api/info")
    def info() -> dict[str, Any]:
        return {"live_model": cfg.name if cfg else None, "runs": len(store.traces)}

    @app.get("/api/runs")
    def runs() -> list[dict[str, Any]]:
        return [_summary(store, t) for t in store.traces.values()]

    @app.get("/api/runs/{trace_id}")
    def run(trace_id: str) -> dict[str, Any]:
        return _detail(store, trace_or_404(trace_id))

    @app.post("/api/runs/{trace_id}/audit")
    def audit_live(trace_id: str) -> dict[str, Any]:  # sync: FastAPI runs it in a worker thread
        trace = trace_or_404(trace_id)
        if cfg is None:
            raise HTTPException(503, "no model configured (set LLM_NAME, LLM_BASE_URL, LLM_API_KEY)")
        if not one_live_audit.acquire(blocking=False):
            raise HTTPException(429, "another live audit is running, try again in a moment")
        try:
            result = audit(trace, policy_for(trace, None), LLMContext(cfg))
        except Exception as e:  # network, auth, model errors: shown to the user without secrets
            raise HTTPException(502, f"audit failed: {redact(str(e))[:300]}") from e
        finally:
            one_live_audit.release()
        store.audits[trace_id] = result
        store.live.add(trace_id)
        return _detail(store, trace)

    def trail() -> dict[str, Any]:
        entries = reviews.entries()
        broken = reviews.verify()
        return {
            "entries": [vars(r) for r in entries[-30:]][::-1],
            "count": len(entries),
            "intact": broken is None,
            "broken_at": broken,
            "latest": {f"{k[0]}#{k[1]}": r.decision for k, r in reviews.latest().items()},
        }

    @app.get("/api/review")
    def review_trail() -> dict[str, Any]:
        return trail()

    @app.post("/api/review")
    def review_add(body: ReviewIn) -> dict[str, Any]:
        """A human decision on one precomputed finding, appended to the hash-chained trail (rosetta_flow.review)."""
        result = store.audits.get(trace_or_404(body.trace_id).trace_id)
        findings = result.report.findings if result and result.report else []
        if not 0 <= body.finding < len(findings):
            raise HTTPException(404, "unknown finding")
        try:
            reviews.add(body.trace_id, body.finding, body.decision, body.reviewer, body.note)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        except OSError as e:
            raise HTTPException(500, f"review log not writable: {e.strerror}") from e
        return trail()

    @app.get("/api/fleet")
    def fleet() -> FileResponse:
        """Measured two-tier test results for the fleet replay (built by app.demo.build_fleet)."""
        if not (demo_dir / "fleet.json").exists():
            raise HTTPException(404, "no fleet data")
        return FileResponse(demo_dir / "fleet.json", media_type="application/json")

    live_runs = live.load(demo_dir / "live")
    pipeline_config = _pipeline_config()

    @app.get("/api/live")
    def live_list() -> dict[str, Any]:
        return {
            "screener": pipeline_config.screener.model,
            "confirmer": pipeline_config.confirmer.model if pipeline_config.confirmer else None,
            "available": cfg is not None,
            "runs": [
                {"trace_id": r.trace.trace_id, "domain": r.trace.domain, "language": r.trace.language,
                 "intent": r.intent.replace("_", " "), "agent": r.trace.agent.description,
                 "spans": [s.model_dump(mode="json", exclude_none=True) for s in r.trace.spans],
                 "sabotage": [{"name": i.name, "text": live.SABOTAGE_TEXT.get(i.name, i.name)}
                              for i in r.sabotage_options()],
                 "tool_docs": {name: t.description for name, t in r.spec.tools.items()}}
                for r in live_runs.values()
            ],
        }  # fmt: skip

    @app.post("/api/live/{trace_id}")
    def live_audit(trace_id: str, sabotage: str = "") -> StreamingResponse:
        if trace_id not in live_runs:
            raise HTTPException(404, "unknown run")
        if cfg is None:
            raise HTTPException(503, "no model configured (set LLM_NAME, LLM_BASE_URL, LLM_API_KEY)")
        if not one_live_audit.acquire(blocking=False):
            raise HTTPException(429, "another live audit is running, try again in a moment")

        def events() -> Iterator[bytes]:  # one JSON object per line, flushed as each tier finishes
            try:
                for event in live.stream(live_runs[trace_id], sabotage or None, pipeline_config, cfg):
                    yield (json.dumps(event, ensure_ascii=False) + "\n").encode()
            finally:
                one_live_audit.release()

        return StreamingResponse(events(), media_type="application/x-ndjson")

    return app


def _pipeline_config() -> PipelineConfig:
    """pipeline.toml next to the working directory, else the shipped two-tier default."""
    path = Path(os.environ.get("ROSETTA_PIPELINE", "pipeline.toml"))
    if path.exists():
        return PipelineConfig.from_toml(path)
    return PipelineConfig(Tier("swiss-ai/Apertus-v1.5-8B"), Tier("swiss-ai/Apertus-v1.5-70B"))
