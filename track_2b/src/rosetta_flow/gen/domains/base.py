"""Shared contract for simulated domains: tools over a seeded world, a written policy and a code policy checker."""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from rosetta_flow.trace import Agent, Domain, ErrorType, LabeledError, Language, Span, SpanKind, Trace


class ToolError(Exception):
    """Business-level failure; surfaces to the agent as a tool_result with status 'error'."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    params: dict[str, dict[str, Any]]
    required: tuple[str, ...]
    fn: Callable[..., Any]

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.params,
                    "required": list(self.required),
                    "additionalProperties": False,
                },
            },
        }


@dataclass(frozen=True)
class Violation:
    rule: str
    error_type: ErrorType
    span_ids: tuple[str, ...]
    detail: str
    # Heuristic rules (keyword or language guesses) are not certain enough to become labels; a trace flagged
    # only by them is set aside as suspect instead of being counted as clean or as an error.
    certain: bool = True

    def as_label_error(self) -> LabeledError:
        return LabeledError(
            type=self.error_type, span_ids=list(self.span_ids), injector=None, note=f"{self.rule}: {self.detail}"
        )


@dataclass(frozen=True)
class Scenario:
    """What the simulated customer wants. Facts are what the customer knows; the agent must find the rest."""

    scenario_id: str
    intent: str
    customer_id: str
    language: Language
    goal: str
    facts: dict[str, str]
    tone: str


@dataclass(frozen=True)
class DomainSpec[W]:
    domain: Domain
    policy_id: str
    policy: str
    agent: Agent
    tools: dict[str, ToolSpec]
    make_world: Callable[[int], W]
    check: Callable[[Trace, W], list[Violation]]
    sample_scenario: Callable[[W, random.Random], Scenario]
    today: date
    tool_order: tuple[str, ...] = field(default=())
    # What the generic error injectors need to know about the domain:
    # guards: state-changing tool -> check that the policy requires before it (skipped/wrong-order errors)
    # action_failures: state-changing tool -> realistic backend error text (ignored-tool-error errors)
    guards: dict[str, str] = field(default_factory=dict)
    action_failures: dict[str, str] = field(default_factory=dict)
    # Who writes to the agent ("customer", "colleague"): wording of the simulated requester and the verbaliser.
    user_role: str = "customer"
    # Trade terms the verbaliser must translate the way the trade does: trigger word -> translations.
    glossary: dict[str, str] = field(default_factory=dict)
    requester: str = "a customer chatting with the online support"
    # Domain flavour of the LLM injectors, so an invented fact or a leak sounds like this domain:
    # invented_fact(rng, numbers already in the trace) -> (fact to state, exact number text it must contain)
    # leak(rng) -> (aside revealing confidential data, exact text it must contain, label note)
    invented_fact: Callable[[random.Random, set[float]], tuple[str, str]] | None = None
    leak: Callable[[random.Random], tuple[str, str, str]] | None = None

    def openai_tools(self) -> list[dict[str, Any]]:
        names = self.tool_order or tuple(self.tools)
        return [self.tools[n].openai_schema() for n in names]

    def call(self, world: W, name: str, args: dict[str, Any]) -> tuple[Literal["ok", "error"], Any]:
        """Execute a tool the way a real backend would: bad input is an error result, never an exception."""
        tool = self.tools.get(name)
        if tool is None:
            return "error", f"unknown tool '{name}'"
        missing = [p for p in tool.required if p not in args]
        unknown = [p for p in args if p not in tool.params]
        if missing or unknown:
            return "error", f"invalid arguments: missing {missing}, unknown {unknown}"
        try:
            return "ok", tool.fn(world, **args)
        except ToolError as e:
            return "error", str(e)
        except (TypeError, ValueError, OverflowError) as e:  # e.g. int(float("inf")) from JSON Infinity
            return "error", f"invalid argument value: {e}"


def tool_exchanges(trace: Trace) -> list[tuple[Span, Span | None]]:
    """Pair each tool_call with its result (None if the trace has no answer for it)."""
    results = {s.call_id: s for s in trace.spans if s.kind is SpanKind.TOOL_RESULT}
    return [(s, results.get(s.call_id)) for s in trace.spans if s.kind is SpanKind.TOOL_CALL]
