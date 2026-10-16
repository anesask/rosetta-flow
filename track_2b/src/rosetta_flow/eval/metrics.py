"""Scoring audits against exact labels.

Conventions (stated in the report): a failed audit (no report) is wrong on every trace, a false alarm on a clean
one and a miss on an error one. Localisation and type are judged on credible findings (a verified quote, at most
MAX_CITED_SPANS cited spans) that overlap a labelled error; labels with several errors count each of them.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from rosetta_flow.harness.audit import AuditResult
from rosetta_flow.harness.schema import AuditReport, Finding
from rosetta_flow.trace import Label, LabeledError, Trace

MAX_CITED_SPANS = 4  # labelled errors span 1 to 3 spans; a wider citation is a guess, not a location


def with_min_confidence(result: AuditResult, threshold: float) -> AuditResult:
    """The audit as if findings below `threshold` confidence had not been reported (a run left without findings
    becomes "ok"). Findings without a confidence are kept. Evidence checks follow their findings' new indices."""
    if result.report is None or threshold <= 0:
        return result
    kept = [i for i, f in enumerate(result.report.findings) if f.confidence is None or f.confidence >= threshold]
    findings = [result.report.findings[i] for i in kept]
    report = AuditReport(verdict="issues_found" if findings else "ok", findings=findings)
    evidence = [replace(e, finding=kept.index(e.finding)) for e in result.evidence if e.finding in kept]
    return replace(result, report=report, evidence=evidence)


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)

    @property
    def false_alarm_rate(self) -> float | None:
        return self.fp / (self.fp + self.tn) if self.fp + self.tn else None

    @property
    def balanced_accuracy(self) -> float | None:
        """Mean of catch rate and clean-pass rate. "Flag everything" scores exactly 0.5, unlike F1 (0.67 at 50 %)."""
        r, fa = self.recall, self.false_alarm_rate
        return (r + (1 - fa)) / 2 if r is not None and fa is not None else None


@dataclass
class Scores:
    system: str
    traces: int
    failed_audits: int
    detection: Counts = field(default_factory=Counts)
    # Strict: a hit needs a finding on a labelled span; a flag on the wrong span is a false alarm and a miss.
    strict: Counts = field(default_factory=Counts)
    located: int = 0  # error traces where a finding overlaps a labelled span
    type_strict: int = 0  # of located: exact type
    type_lenient: int = 0  # of located: exact or acceptable type
    findings: int = 0
    findings_verified: int = 0
    audited: int = 0  # audits present; per-trace costs average over these, not over the labels
    tool_calls: int = 0
    duration_s: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    by_type: dict[str, Counts] = field(default_factory=lambda: defaultdict(Counts))
    by_language: dict[str, Counts] = field(default_factory=lambda: defaultdict(Counts))

    def summary(self) -> dict[str, Any]:
        d, n = self.detection, max(1, self.audited)
        errors = d.tp + d.fn
        return {
            "system": self.system,
            "traces": self.traces,
            "error_traces": errors,
            "balanced_accuracy": _r(d.balanced_accuracy),
            "strict_f1": _r(self.strict.f1),
            "strict_precision": _r(self.strict.precision),
            "strict_recall": _r(self.strict.recall),
            "precision": _r(d.precision),
            "recall": _r(d.recall),
            "f1": _r(d.f1),
            "false_alarm_rate": _r(d.false_alarm_rate),
            "localisation_recall": _r(self.located / errors if errors else None),
            "type_accuracy_strict": _r(self.type_strict / self.located if self.located else None),
            "type_accuracy_lenient": _r(self.type_lenient / self.located if self.located else None),
            "evidence_verified": _r(self.findings_verified / self.findings if self.findings else None),
            "failed_audits": self.failed_audits,
            "tool_calls_mean": round(self.tool_calls / n, 1),
            "duration_s_mean": round(self.duration_s / n, 1),
            "tokens_per_trace": round((self.prompt_tokens + self.completion_tokens) / n),
            "recall_by_type": {k: _r(v.recall) for k, v in sorted(self.by_type.items())},
            "by_language": {
                k: {"recall": _r(v.recall), "false_alarm_rate": _r(v.false_alarm_rate)}
                for k, v in sorted(self.by_language.items())
            },
        }


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 3)


def score(system: str, traces: dict[str, Trace], labels: dict[str, Label], audits: dict[str, AuditResult]) -> Scores:
    s = Scores(system=system, traces=len(labels), failed_audits=0)
    for tid, label in labels.items():
        result = audits.get(tid)
        report = result.report if result else None
        failed = report is None
        s.failed_audits += failed
        flagged = not failed and report.verdict == "issues_found"
        # A failed audit is wrong on every trace: counting it as "no alarm" made failing on clean traces score as
        # a correct pass, so a system that failed often looked careful.
        wrong_on_clean = flagged or failed
        is_error = not label.is_clean
        lang = traces[tid].language if tid in traces else "?"
        for bucket in (s.detection, s.by_language[lang]):
            bucket.tp += is_error and flagged
            bucket.fn += is_error and not flagged
            bucket.fp += (not is_error) and wrong_on_clean
            bucket.tn += (not is_error) and not wrong_on_clean
        if result is not None:
            s.audited += 1
            s.tool_calls += result.tool_calls
            s.duration_s += result.duration_s
            s.prompt_tokens += result.usage.get("prompt_tokens", 0)
            s.completion_tokens += result.usage.get("completion_tokens", 0)
            s.findings += len(result.evidence)
            s.findings_verified += sum(e.verified for e in result.evidence)
        if not is_error:
            s.strict.fp += wrong_on_clean
            s.strict.tn += not wrong_on_clean
            continue
        counted = _credible_findings(result)
        overlapping = [f for f in counted if any(set(f.span_ids) & set(e.span_ids) for e in label.errors)]
        hit = bool(overlapping)
        s.located += hit
        s.strict.tp += hit
        s.strict.fn += not hit
        s.strict.fp += flagged and not hit
        s.type_strict += any(f.error_type == e.type for f in overlapping for e in _matched(f, label))
        s.type_lenient += any(
            f.error_type == e.type or f.error_type in e.acceptable_types
            for f in overlapping
            for e in _matched(f, label)
        )
        for e in label.errors:
            caught = any(set(f.span_ids) & set(e.span_ids) for f in counted)
            bucket = s.by_type[e.injector or e.type.value]
            bucket.tp += caught
            bucket.fn += not caught
    return s


def _credible_findings(result: AuditResult | None) -> list[Finding]:
    """Findings that may count as locating an error: a verified quote and a focused citation. Without these
    rules, citing every span with invented quotes "located" every error (strict F1 0.67 for flag-everything)."""
    if result is None or result.report is None:
        return []
    # At least one quote must really be in a cited span: that proves the model read the place it points at, while
    # an extra policy line quoted as "evidence" (common, and harmless) does not erase a correct location.
    unverified = {e.finding: len(e.unverified_quotes) for e in result.evidence}
    return [
        f
        for i, f in enumerate(result.report.findings)
        if unverified.get(i, len(f.evidence)) < len(f.evidence) and len(set(f.span_ids)) <= MAX_CITED_SPANS
    ]


def _matched(finding: Finding, label: Label) -> list[LabeledError]:
    return [e for e in label.errors if set(finding.span_ids) & set(e.span_ids)]


def investigation_matches(result: AuditResult, label: Label) -> tuple[bool, str]:
    """Whether an audit is good enough to be imitated in training, with the reason if not.

    Stricter than scoring, because a kept investigation teaches everything in it: on a clean trace the report
    must be "ok"; on an error trace every finding must sit on a labelled error (no false alarm alongside the hit),
    every quote must verify, and one finding must be a credible hit with an acceptable type.
    """
    report = result.report
    if report is None:
        return False, f"no report ({result.failure})"
    if label.is_clean:
        ok = report.verdict == "ok" and not report.findings
        return ok, "" if ok else "false alarm on a clean trace"
    if report.verdict != "issues_found" or not report.findings:
        return False, "missed the error"
    if stray := [f for f in report.findings if not _matched(f, label)]:
        return False, f"{len(stray)} finding(s) on unlabelled spans"
    if any(not e.verified for e in result.evidence):
        return False, "unverified quote"
    good = any(
        f.error_type == e.type or f.error_type in e.acceptable_types
        for f in _credible_findings(result)
        for e in _matched(f, label)
    )
    return good, "" if good else "wrong error type or citation too broad"


TABLE_COLUMNS = [
    ("System", "system"),
    ("Balanced acc.", "balanced_accuracy"),
    ("Strict F1", "strict_f1"),
    ("Detection F1", "f1"),
    ("Recall", "recall"),
    ("False alarms", "false_alarm_rate"),
    ("Right step", "localisation_recall"),
    ("Type (strict/lenient)", None),
    ("Evidence verified", "evidence_verified"),
    ("Failed audits", "failed_audits"),
    ("Tool calls", "tool_calls_mean"),
    ("s / trace", "duration_s_mean"),
    ("Tokens / trace", "tokens_per_trace"),
]


def markdown_table(summaries: list[dict[str, Any]]) -> str:
    def cell(s: dict[str, Any], key: str | None) -> str:
        if key is None:
            return f"{_fmt(s['type_accuracy_strict'])} / {_fmt(s['type_accuracy_lenient'])}"
        return _fmt(s[key])

    head = "| " + " | ".join(name for name, _ in TABLE_COLUMNS) + " |"
    sep = "|" + "|".join("---" for _ in TABLE_COLUMNS) + "|"
    rows = ["| " + " | ".join(cell(s, key) for _, key in TABLE_COLUMNS) + " |" for s in summaries]
    return "\n".join([head, sep, *rows])


def recall_by_type_table(summaries: list[dict[str, Any]]) -> str:
    types = sorted({t for s in summaries for t in s["recall_by_type"]})
    head = "| Error type | " + " | ".join(s["system"] for s in summaries) + " |"
    sep = "|---|" + "|".join("---" for _ in summaries) + "|"
    rows = [f"| {t} | " + " | ".join(_fmt(s["recall_by_type"].get(t)) for s in summaries) + " |" for t in types]
    return "\n".join([head, sep, *rows])


def _fmt(v: Any) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def as_dict(scores: Scores) -> dict[str, Any]:
    d = asdict(scores)
    d["summary"] = scores.summary()
    return d
