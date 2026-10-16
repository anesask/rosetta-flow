"""Trace schema and the trace-as-repo virtual file tree."""

from rosetta_flow.trace.io import index_by, read_jsonl, write_jsonl
from rosetta_flow.trace.models import (
    Agent,
    Domain,
    ErrorType,
    Label,
    LabeledError,
    Language,
    Span,
    SpanKind,
    Trace,
    check_label,
)
from rosetta_flow.trace.repo import SearchError, SearchHit, TraceRepo, normalize, normalize_span_id, render_span

__all__ = [
    "Agent",
    "Domain",
    "ErrorType",
    "Label",
    "LabeledError",
    "Language",
    "SearchError",
    "SearchHit",
    "Span",
    "SpanKind",
    "Trace",
    "TraceRepo",
    "check_label",
    "index_by",
    "normalize",
    "normalize_span_id",
    "read_jsonl",
    "render_span",
    "write_jsonl",
]
