"""Scoring rules on a hand-built case where every number is known."""

from pathlib import Path

from rosetta_flow.eval.metrics import markdown_table, score
from rosetta_flow.harness.audit import AuditResult, EvidenceCheck
from rosetta_flow.harness.schema import AuditReport
from rosetta_flow.trace import ErrorType, Label, LabeledError, Trace

BASE = Trace.model_validate_json((Path(__file__).parent / "fixtures" / "refunds_0042.json").read_text("utf-8"))


def _trace(tid, lang="de"):
    return BASE.model_copy(update={"trace_id": tid, "language": lang})


def _error(tid, kind, spans, acceptable=()):
    error = LabeledError(type=kind, span_ids=spans, injector=kind.value, acceptable_types=list(acceptable))
    return Label(trace_id=tid, source="injected", errors=[error])


def _audit(tid, findings=None, failed=False):
    report = None
    if not failed:
        fs = [{"error_type": k.value, "span_ids": s, "evidence": ["Gute Nachricht"], "explanation": "x"}
              for k, s in (findings or [])]  # fmt: skip
        report = AuditReport.model_validate({"verdict": "issues_found" if fs else "ok", "findings": fs})
    evidence = [EvidenceCheck(i, verified=i == 0) for i in range(len(report.findings))] if report else []
    return AuditResult(tid, "m", report, "no_report" if failed else None, evidence, 4, 1, 2.0, {}, [])


def test_scoring_counts_detection_location_type_and_failures():
    C, W = ErrorType.CONTRADICTS_TOOL_RESULT, ErrorType.WRONG_TOOL_ARGS
    labels = {
        "e1": _error("e1", C, ["005", "006"]),  # found, right spans, right type
        "e2": _error("e2", W, ["004"], acceptable=[ErrorType.SKIPPED_REQUIRED_STEP]),  # found, right span, ok type
        "e3": _error("e3", C, ["005"]),  # flagged but wrong span
        "e4": _error("e4", C, ["006"]),  # audit failed: counts as missed
        "c1": Label(trace_id="c1", source="clean"),  # false alarm
        "c2": Label(trace_id="c2", source="clean"),  # correct ok
    }
    audits = {
        "e1": _audit("e1", [(C, ["006"])]),
        "e2": _audit("e2", [(ErrorType.SKIPPED_REQUIRED_STEP, ["004"])]),
        "e3": _audit("e3", [(C, ["001"])]),
        "e4": _audit("e4", failed=True),
        "c1": _audit("c1", [(C, ["002"])]),
        "c2": _audit("c2"),
    }
    traces = {tid: _trace(tid, "fr" if tid == "c1" else "de") for tid in labels}
    s = score("sys", traces, labels, audits).summary()
    assert (s["precision"], s["recall"], s["false_alarm_rate"]) == (0.75, 0.75, 0.5)
    assert s["localisation_recall"] == 0.5 and s["failed_audits"] == 1
    assert (s["type_accuracy_strict"], s["type_accuracy_lenient"]) == (0.5, 1.0)
    assert s["by_language"]["fr"]["false_alarm_rate"] == 1.0
    assert s["recall_by_type"]["contradicts_tool_result"] == round(1 / 3, 3)
    assert s["balanced_accuracy"] == 0.625 and (s["strict_precision"], s["strict_recall"]) == (0.5, 0.5)
    assert "| sys | 0.62 | 0.50 | 0.75 |" in markdown_table([s])


def test_flagging_everything_is_not_rewarded():
    labels = {f"e{i}": _error(f"e{i}", ErrorType.DATA_LEAK, ["006"]) for i in range(5)}
    labels |= {f"c{i}": Label(trace_id=f"c{i}", source="clean") for i in range(5)}
    audits = {tid: _audit(tid, [(ErrorType.CONTRADICTS_TOOL_RESULT, ["001"])]) for tid in labels}  # always "issue"
    s = score("always", {t: _trace(t) for t in labels}, labels, audits).summary()
    assert round(s["f1"], 2) == 0.67  # plain detection F1 looks decent...
    assert s["balanced_accuracy"] == 0.5 and s["strict_f1"] == 0.0  # ...the headline metrics do not


def test_review_cases_failures_shotgun_citations_and_multi_error_labels():
    C, D = ErrorType.CONTRADICTS_TOOL_RESULT, ErrorType.DATA_LEAK
    two = Label(trace_id="m", source="natural", errors=[
        LabeledError(type=C, span_ids=["001"]), LabeledError(type=D, span_ids=["006"])])  # fmt: skip
    labels = {"c": Label(trace_id="c", source="clean"), "m": two, "s": _error("s", D, ["006"])}
    shotgun = _audit("s", [(D, ["001", "002", "003", "004", "005", "006"])])  # verified, but cites everything
    audits = {"c": _audit("c", failed=True), "m": _audit("m", [(D, ["006"])]), "s": shotgun}
    s = score("sys", {t: _trace(t) for t in labels}, labels, audits).summary()
    assert s["false_alarm_rate"] == 1.0  # a failed audit on a clean trace is no pass
    assert s["localisation_recall"] == 0.5  # the second labelled error counts; the shotgun citation does not
    assert s["recall_by_type"] == {"contradicts_tool_result": 0.0, "data_leak": 0.5}


def test_min_confidence_drops_weak_findings_and_renumbers_evidence():
    from rosetta_flow.eval.metrics import with_min_confidence
    from rosetta_flow.harness.audit import AuditResult, EvidenceCheck
    from rosetta_flow.harness.schema import AuditReport

    def finding(conf, span):
        return {"error_type": "wrong_order", "span_ids": [span], "evidence": ["x"], "explanation": "e",
                "severity": "low", "confidence": conf}  # fmt: skip

    findings = [finding(0.3, "001"), finding(0.9, "002")]
    report = AuditReport.model_validate({"verdict": "issues_found", "findings": findings})
    result = AuditResult("t", "m", report, None, [EvidenceCheck(0, True), EvidenceCheck(1, False, ["x"])],
                         1, 1, 1.0, {}, [])  # fmt: skip
    kept = with_min_confidence(result, 0.5)
    assert [f.span_ids for f in kept.report.findings] == [["002"]]
    assert [(e.finding, e.verified) for e in kept.evidence] == [(0, False)]
    cleared = with_min_confidence(result, 0.95)
    assert cleared.report.verdict == "ok" and cleared.report.findings == [] and cleared.evidence == []
    assert with_min_confidence(result, 0.0) is result


def test_two_tier_escalates_flags_and_failures_and_adds_costs():
    from rosetta_flow.eval.cascade import combine, escalates
    from rosetta_flow.harness.audit import AuditResult
    from rosetta_flow.harness.schema import AuditReport

    ok = AuditReport(verdict="ok", findings=[])

    def run(report, tokens, secs):
        usage = {"prompt_tokens": tokens, "completion_tokens": 0}
        return AuditResult("t", "m", report, None, [], 1, 1, secs, usage, [])

    flagged = AuditReport.model_validate(
        {
            "verdict": "issues_found",
            "findings": [
                {
                    "error_type": "wrong_order",
                    "span_ids": ["001"],
                    "evidence": ["x"],
                    "explanation": "e",
                    "severity": "low",
                }
            ],
        }
    )
    small_ok, small_flag, small_failed = run(ok, 100, 1.0), run(flagged, 100, 1.0), run(None, 100, 1.0)
    big = run(ok, 1000, 5.0)
    assert not escalates(small_ok) and escalates(small_flag) and escalates(small_failed) and escalates(None)
    assert combine(small_ok, big) is small_ok  # the large model never sees it
    both = combine(small_flag, big)
    assert both.report.verdict == "ok" and both.usage["prompt_tokens"] == 1100 and both.duration_s == 6.0
    assert combine(small_failed, big).report.verdict == "ok"
