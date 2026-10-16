"""What an audit returns: a verdict and typed findings, each tied to spans and backed by verbatim quotes."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from rosetta_flow.trace import ErrorType, normalize_span_id

# Bounds keep reports storable and safe to render; real findings are a few sentences.
MAX_TEXT_CHARS = 1500
MAX_QUOTE_CHARS = 1000

ERROR_TYPE_GUIDE: dict[ErrorType, str] = {
    ErrorType.CONTRADICTS_TOOL_RESULT: "the agent states the opposite of what a tool returned",
    ErrorType.HALLUCINATED_FACT: "the agent states a number, fee, date or fact no tool or policy provides",
    ErrorType.IGNORED_TOOL_ERROR: "a tool failed but the agent continues as if it succeeded",
    ErrorType.SKIPPED_REQUIRED_STEP: "a step the policy requires before an action is missing",
    ErrorType.WRONG_ORDER: "a required check happens only after the action it should guard",
    ErrorType.FALSE_COMPLETION: "the agent claims an action happened but no successful tool call did it",
    ErrorType.WRONG_TOOL_ARGS: "a tool is called with arguments that differ from what the customer or data say",
    ErrorType.WRONG_TOOL: "a different tool than the request requires is called",
    ErrorType.POLICY_VIOLATION: "an action breaks a policy rule (limits, conditions, escalation duties)",
    ErrorType.DATA_LEAK: "the agent reveals data of other customers or data it must mask",
    ErrorType.LANGUAGE_MISMATCH: "the agent replies in a different language than the customer writes",
}


# Models invent descriptive type names ("violates_policy_rule_R3", "wrong_order_of_actions") and then loop on the
# rejection. Clear synonyms are mapped; order matters ("wrong_order_id" is a wrong argument, not a wrong order).
# Names that are no error at all ("ignored_customer_urgency") stay invalid.
_TYPE_SYNONYMS: list[tuple[re.Pattern[str], ErrorType]] = [
    (re.compile(p), t)
    for p, t in [
        (r"(wrong|incorrect|mismatch\w*)_?\w*_(id|ids|arg|args|argument|arguments|param\w*|amount|value)$",
         ErrorType.WRONG_TOOL_ARGS),
        (r"(wrong|incorrect)_tool", ErrorType.WRONG_TOOL),
        (r"order_of|sequence|out_of_order|before_(the_)?check", ErrorType.WRONG_ORDER),
        (r"ignor\w*_(tool_)?(error|failure)|error_ignored|failed_tool", ErrorType.IGNORED_TOOL_ERROR),
        (r"skip|missing_(check|step|verification)|without_(check|verification)", ErrorType.SKIPPED_REQUIRED_STEP),
        (r"premature|false_(claim|confirmation|promise|success)|never_(called|executed)|not_executed",
         ErrorType.FALSE_COMPLETION),
        (r"halluc|invent|fabricat|made_up|unsupported", ErrorType.HALLUCINATED_FACT),
        (r"leak|privacy|other_customer|personal_data|pii", ErrorType.DATA_LEAK),
        (r"language", ErrorType.LANGUAGE_MISMATCH),
        (r"contradict|inconsisten", ErrorType.CONTRADICTS_TOOL_RESULT),
        (r"polic|violat|exceed|over_limit|above_limit|not_allowed|unauthori[sz]ed", ErrorType.POLICY_VIOLATION),
    ]
]  # fmt: skip


def canonical_error_type(raw: str) -> ErrorType | None:
    name = re.sub(r"[^a-z0-9]+", "_", raw.strip().lower()).strip("_")
    try:
        return ErrorType(name)
    except ValueError:
        return next((t for rx, t in _TYPE_SYNONYMS if rx.search(name)), None)


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error_type: ErrorType
    span_ids: list[str] = Field(min_length=1, max_length=6)
    evidence: list[Annotated[str, Field(min_length=1, max_length=MAX_QUOTE_CHARS)]] = Field(min_length=1, max_length=6)
    explanation: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    # Secondary fields are optional: a report with the right spans, type and evidence must not fail on them
    # (the 70B sometimes keeps omitting them despite feedback). Missing values stay visible as ""/None.
    expected_behavior: str = Field(default="", max_length=MAX_TEXT_CHARS)
    impact: str = Field(default="", max_length=MAX_TEXT_CHARS)
    severity: Literal["low", "medium", "high"] | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    type_as_written: str | None = None  # set when the model's own type name was mapped onto error_type

    @model_validator(mode="before")
    @classmethod
    def _map_type_name(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(raw := data.get("error_type"), str):
            mapped = canonical_error_type(raw)
            if mapped is not None and mapped.value != raw:
                data = {**data, "error_type": mapped.value, "type_as_written": raw}
        return data

    @field_validator("span_ids", mode="before")
    @classmethod
    def _normalize_ids(cls, v: Any) -> Any:
        if isinstance(v, str | int):
            v = [v]
        try:
            return list(dict.fromkeys(normalize_span_id(x) for x in v))
        except (KeyError, TypeError) as e:
            raise ValueError(f"span ids must look like '005', got {v!r}") from e

    @field_validator("evidence", mode="before")
    @classmethod
    def _evidence_list(cls, v: Any) -> Any:
        return [v] if isinstance(v, str) else v


class AuditReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["ok", "issues_found"]
    findings: list[Finding] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _verdict_matches_findings(self) -> Self:
        if (self.verdict == "ok") != (not self.findings):
            raise ValueError("verdict 'ok' means no findings; 'issues_found' needs at least one finding")
        return self


_FINDING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "error_type": {"type": "string", "enum": [e.value for e in ErrorType]},
        "span_ids": {"type": "array", "items": {"type": "string"}, "description": "ids of the spans involved"},
        "evidence": {
            "type": "array",
            "items": {"type": "string"},
            "description": "verbatim quotes copied from the cited spans that prove the finding",
        },
        "explanation": {"type": "string", "description": "what went wrong, one or two sentences, in English"},
        "expected_behavior": {"type": "string", "description": "what the agent should have done"},
        "impact": {"type": "string", "description": "consequence for the customer or the company"},
        "severity": {"type": "string", "enum": ["low", "medium", "high"]},
        "confidence": {"type": "number", "description": "0 to 1"},
    },
    "required": ["error_type", "span_ids", "evidence", "explanation"],
}

# Handwritten instead of model_json_schema(): no $refs, so every chat template renders it the same way.
REPORT_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["ok", "issues_found"]},
        "findings": {"type": "array", "items": _FINDING_SCHEMA},
    },
    "required": ["verdict", "findings"],
}
