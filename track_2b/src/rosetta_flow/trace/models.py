"""Canonical trace format: every component (generator, harness, training, eval, UI) uses only these models."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0"

Language = Literal["de", "fr", "it", "en"]


class Domain(StrEnum):
    BANKING = "banking"
    REFUNDS = "refunds"
    MANUFACTURING = "manufacturing"
    IT_HELPDESK = "it_helpdesk"
    # External runs for evaluation only (tau-bench, Sierra, MIT): policies come with the run, not from our domains.
    AIRLINE = "airline"
    RETAIL = "retail"


class SpanKind(StrEnum):
    USER_MESSAGE = "user_message"
    AGENT_MESSAGE = "agent_message"
    LLM_REASONING = "llm_reasoning"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    # Unmapped spans from imported OTel traces; kept readable for the auditor.
    OTHER = "other"


TEXT_KINDS = {SpanKind.USER_MESSAGE, SpanKind.AGENT_MESSAGE, SpanKind.LLM_REASONING, SpanKind.OTHER}


class ErrorType(StrEnum):
    CONTRADICTS_TOOL_RESULT = "contradicts_tool_result"
    HALLUCINATED_FACT = "hallucinated_fact"
    IGNORED_TOOL_ERROR = "ignored_tool_error"
    SKIPPED_REQUIRED_STEP = "skipped_required_step"
    WRONG_ORDER = "wrong_order"
    FALSE_COMPLETION = "false_completion"
    WRONG_TOOL_ARGS = "wrong_tool_args"
    WRONG_TOOL = "wrong_tool"
    POLICY_VIOLATION = "policy_violation"
    DATA_LEAK = "data_leak"
    LANGUAGE_MISMATCH = "language_mismatch"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Span(_Strict):
    id: str = Field(pattern=r"^\d{3}$")
    kind: SpanKind
    text: str | None = None
    tool: str | None = None
    args: dict[str, Any] | None = None
    call_id: str | None = None
    status: Literal["ok", "error"] | None = None
    result: Any = None
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _fields_match_kind(self) -> Self:
        if self.kind in TEXT_KINDS and self.text is None:
            raise ValueError(f"span {self.id}: {self.kind} needs text")
        if self.kind is SpanKind.TOOL_CALL and not (self.tool and self.call_id):
            raise ValueError(f"span {self.id}: tool_call needs tool and call_id")
        if self.kind is SpanKind.TOOL_RESULT and not (self.call_id and self.status):
            raise ValueError(f"span {self.id}: tool_result needs call_id and status")
        if self.start_ms is not None and self.end_ms is not None and self.end_ms < self.start_ms:
            raise ValueError(f"span {self.id}: end_ms before start_ms")
        return self


class Agent(_Strict):
    name: str
    description: str


class Trace(_Strict):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    trace_id: str
    domain: Domain
    language: Language
    agent: Agent
    policy_id: str
    spans: list[Span] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent_spans(self) -> Self:
        # Ids must be dense and ordered: auditors cite them and injectors renumber after deletions.
        expected = [f"{i:03d}" for i in range(len(self.spans))]
        if [s.id for s in self.spans] != expected:
            raise ValueError("span ids must be 000, 001, ... in order")
        open_calls: set[str] = set()
        for s in self.spans:
            if s.kind is SpanKind.TOOL_CALL:
                if s.call_id in open_calls:
                    raise ValueError(f"span {s.id}: duplicate call_id {s.call_id}")
                open_calls.add(s.call_id)
            elif s.kind is SpanKind.TOOL_RESULT:
                if s.call_id not in open_calls:
                    raise ValueError(f"span {s.id}: result for unknown or already answered call {s.call_id}")
                open_calls.discard(s.call_id)
        return self

    def span(self, span_id: str) -> Span:
        for s in self.spans:
            if s.id == span_id:
                return s
        raise KeyError(span_id)

    def with_spans(self, spans: list[Span]) -> tuple[Trace, dict[str, str]]:
        """Rebuild with dense ids. Returns the old-to-new id map so labels can be remapped."""
        if len({s.id for s in spans}) != len(spans):
            raise ValueError("with_spans got duplicate span ids; copy a span with a fresh id before reusing it")
        mapping = {s.id: f"{i:03d}" for i, s in enumerate(spans)}
        renumbered = [s.model_copy(update={"id": mapping[s.id]}) for s in spans]
        return self.model_copy(update={"spans": renumbered}).validated(), mapping

    def validated(self) -> Trace:
        return Trace.model_validate(self.model_dump())


class LabeledError(_Strict):
    type: ErrorType
    span_ids: list[Annotated[str, Field(pattern=r"^\d{3}$")]] = Field(min_length=1)
    injector: str | None = None
    note: str = ""
    # Types that are also correct for this edit (e.g. a refund for the wrong order also lacks its eligibility check).
    acceptable_types: list[ErrorType] = Field(default_factory=list)


class Label(_Strict):
    """Ground truth for one trace. Stored apart from the trace and never shown to the auditor."""

    trace_id: str
    source: Literal["clean", "injected", "natural"]
    errors: list[LabeledError] = Field(default_factory=list)

    @model_validator(mode="after")
    def _source_matches_errors(self) -> Self:
        if (self.source == "clean") != (not self.errors):
            raise ValueError("source 'clean' iff no errors")
        return self

    @property
    def is_clean(self) -> bool:
        return not self.errors

    def remapped(self, mapping: dict[str, str]) -> Label:
        """Apply a Trace.with_spans id map; fails if a labelled span was deleted."""
        errors = []
        for e in self.errors:
            missing = [sid for sid in e.span_ids if sid not in mapping]
            if missing:
                raise ValueError(f"labelled spans {missing} no longer exist")
            errors.append(e.model_copy(update={"span_ids": [mapping[sid] for sid in e.span_ids]}))
        return self.model_copy(update={"errors": errors})


def check_label(trace: Trace, label: Label) -> None:
    """Raise if a label does not belong to the trace or cites spans the trace does not have."""
    if label.trace_id != trace.trace_id:
        raise ValueError(f"label for {label.trace_id} attached to trace {trace.trace_id}")
    ids = {s.id for s in trace.spans}
    for e in label.errors:
        if missing := [sid for sid in e.span_ids if sid not in ids]:
            raise ValueError(f"{trace.trace_id}: label cites missing spans {missing}")
