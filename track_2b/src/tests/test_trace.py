import contextlib
import json
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from rosetta_flow.trace import (
    ErrorType,
    Label,
    LabeledError,
    SearchError,
    Span,
    SpanKind,
    Trace,
    TraceRepo,
    check_label,
    normalize_span_id,
    read_jsonl,
    write_jsonl,
)

FIXTURE = Path(__file__).parent / "fixtures" / "refunds_0042.json"


@pytest.fixture
def raw() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def trace(raw) -> Trace:
    return Trace.model_validate(raw)


@pytest.fixture
def repo(trace) -> TraceRepo:
    return TraceRepo(trace, "R1 never refund if eligible is false.")


def _err(kind, *ids):
    return LabeledError(type=kind, span_ids=list(ids))


def test_trace_validation_rejects_every_malformed_shape(raw):
    assert len(Trace.model_validate(raw).spans) == 7

    def broken(mutate):
        r = json.loads(json.dumps(raw))
        mutate(r["spans"])
        return r

    def result_before_call(s):
        s[2], s[3] = {**s[3], "id": "002"}, {**s[2], "id": "003"}

    cases = {  # each must fail for its own reason, not for a side effect of the mutation
        "gap in ids": (lambda s: s[3].update(id="009"), "000, 001"),
        "result for unknown call": (lambda s: s[5].update(call_id="c9"), "unknown or already answered"),
        "second result for one call": (lambda s: s[5].update(call_id="c1"), "unknown or already answered"),
        "result before its call": (result_before_call, "unknown or already answered"),
        "tool call without tool": (lambda s: s[2].pop("tool"), "needs tool"),
        "message without text": (lambda s: s[0].pop("text"), "needs text"),
        "unknown field": (lambda s: s[0].update(confidence=0.9), "Extra inputs"),
        "end before start": (lambda s: s[0].update(start_ms=10, end_ms=5), "end_ms before start_ms"),
    }
    for name, (mutate, reason) in cases.items():
        with pytest.raises(ValidationError, match=reason):
            Trace.model_validate(broken(mutate))
            pytest.fail(name)


def test_renumbering_keeps_labels_exact(trace):
    # what a skipped_required_step injector does: drop the eligibility call and its result
    new, mapping = trace.with_spans([s for s in trace.spans if s.id not in {"004", "005"}])
    assert [s.id for s in new.spans] == ["000", "001", "002", "003", "004"]
    assert new.span("004").kind is SpanKind.AGENT_MESSAGE

    label = Label(trace_id=trace.trace_id, source="injected", errors=[_err(ErrorType.SKIPPED_REQUIRED_STEP, "006")])
    moved = label.remapped(mapping)
    assert moved.errors[0].span_ids == ["004"]
    check_label(new, moved)

    stale = Label(trace_id=trace.trace_id, source="injected", errors=[_err(ErrorType.WRONG_TOOL, "005")])
    with pytest.raises(ValueError, match="no longer exist"):
        stale.remapped(mapping)
    with pytest.raises(ValueError, match="duplicate"):
        trace.with_spans([trace.spans[0], trace.spans[0]])


def test_label_invariants(trace):
    with pytest.raises(ValidationError):
        Label(trace_id="t", source="clean", errors=[_err(ErrorType.WRONG_TOOL, "001")])
    with pytest.raises(ValidationError):
        Label(trace_id="t", source="injected")
    with pytest.raises(ValidationError):
        _err(ErrorType.WRONG_TOOL, "5")  # span ids are always the three-digit form
    with pytest.raises(ValueError, match="missing spans"):
        check_label(trace, Label(trace_id=trace.trace_id, source="natural", errors=[_err(ErrorType.DATA_LEAK, "042")]))
    with pytest.raises(ValueError, match="attached to trace"):
        check_label(trace, Label(trace_id="other", source="clean"))


def test_jsonl_roundtrip_is_atomic_and_reports_bad_lines(tmp_path, trace):
    path = tmp_path / "traces.jsonl"
    assert write_jsonl(path, [trace, trace]) == 2
    assert list(read_jsonl(path, Trace)) == [trace, trace]
    assert "Rückerstattung" in path.read_text(encoding="utf-8")
    assert not list(tmp_path.glob("*.tmp"))

    def exploding():
        yield trace
        raise RuntimeError("crash mid-write")

    with pytest.raises(RuntimeError):
        write_jsonl(path, exploding())
    assert list(read_jsonl(path, Trace)) == [trace, trace]  # previous file untouched

    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"trace_id": "x"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match=r"bad\.jsonl:1"):
        list(read_jsonl(bad, Trace))


def test_repo_view_and_lenient_span_ids(repo):
    listing = repo.list_spans()
    assert listing.splitlines()[0] == "trace refunds-0042 (refunds, de), 7 spans"
    assert "004  tool_call:check_refund_eligibility" in listing
    assert "005  tool_result [ok]" in listing
    assert repo.read_span("005").splitlines() == [
        "span 005 | tool_result | call c2 | status ok",
        '{"eligible": false, "reason": "outside_window"}',
    ]
    for alias in (5, "5", "05", "span 005", "#005"):
        assert repo.read_span(alias) == repo.read_span("005")
    for bad in ("099", "abc", None, True):
        with pytest.raises(KeyError):
            repo.read_span(bad)


def test_search_is_useful_and_cannot_crash_or_hang(repo, trace):
    assert [h.span_id for h in repo.search("ELIGIB")] == ["001", "004", "005"]
    assert [h.span_id for h in repo.search(r"CHF\s+\d+", regex=True)] == ["006"]
    assert [h.span_id for h in repo.search("(", regex=False)] == ["002", "004"]  # literal, not a broken regex
    for bad, regex in [("", False), ("   ", False), ("x" * 500, False), ("(", True)]:
        with pytest.raises(SearchError):
            repo.search(bad, regex=regex)
    # Catastrophic patterns the reviewers found past the old shape check end at the time limit, not after minutes.
    slow = TraceRepo(
        trace.model_copy(update={"spans": [Span(id="000", kind=SpanKind.OTHER, text="a" * 3000 + "!")]}), ""
    )
    for pattern in ["(a|a)*$", "((a+))+$", ".*.*.*.*.*.*x"]:
        t0 = time.perf_counter()
        with contextlib.suppress(SearchError):  # "too long", or a quick answer
            slow.search(pattern, regex=True)
        assert time.perf_counter() - t0 < 2.0
    huge = TraceRepo(trace.model_copy(update={"spans": [Span(id="000", kind=SpanKind.OTHER, text="z" * 200_000)]}), "")
    assert len(huge.search("[\\s\\S]*", regex=True)[0].snippet) < 400  # snippets stay small


def test_evidence_check_accepts_faithful_quotes_only(repo):
    faithful = [
        ("006", "Rückerstattung von CHF 129.90 wurde   genehmigt"),  # whitespace
        ("006", "Rückerstattung"),  # decomposed umlaut
        ("005", '"eligible": false'),  # exact JSON
        ("005", "eligible: false"),  # quote marks dropped
        ("006", "Gute Nachricht! ... wurde genehmigt"),  # ellipsis between fragments
        ("006", "gute nachricht"),  # case
        (6, "genehmigt"),  # lenient id
    ]
    fabricated = [
        ("006", '"eligible": false'),  # true quote, wrong span
        ("006", "wurde genehmigt ... Gute Nachricht"),  # fragments out of order
        ("006", "wurde abgelehnt"),
        ("006", "   "),
        ("006", "ok"),  # too short to count as evidence
        ("099", "anything"),
    ]
    assert all(repo.contains(sid, q) for sid, q in faithful)
    assert not any(repo.contains(sid, q) for sid, q in fabricated)


def test_evidence_review_cases(trace):
    """Reviewer findings: tiny fragments verified anything; JSON-escaped and fenced quotes never verified."""
    note = {"note": 'Kunde schrieb: "bitte sofort"\nDanke', "x": "a<<<b>>>c tail text"}
    spans = [*trace.spans[:5], trace.spans[5].model_copy(update={"result": note}), *trace.spans[6:]]
    repo = TraceRepo(trace.model_copy(update={"spans": spans}), "")
    assert not repo.contains("006", "Gute ... Ihre ... von")
    assert repo.contains("005", 'Kunde schrieb: "bitte sofort"') and repo.contains("005", "bitte sofort Danke")
    assert repo.contains("005", "a‹‹‹b›››c tail text")
    assert [normalize_span_id(x) for x in (5, "005", "span 5", "#005", "trace_0042 span 005")] == ["005"] * 5
    for bad in ("005-006", "0042 5", -3, "1000", True):
        with pytest.raises(KeyError):
            normalize_span_id(bad)
