"""Simulated agent domains. Each exposes a DomainSpec: tools, seeded world, policy text and policy checker."""

from rosetta_flow.gen.domains import manufacturing, refunds
from rosetta_flow.gen.domains.base import DomainSpec, ToolError, ToolSpec, Violation, tool_exchanges
from rosetta_flow.trace import Domain

DOMAINS: dict[Domain, DomainSpec] = {Domain.REFUNDS: refunds.SPEC, Domain.MANUFACTURING: manufacturing.SPEC}

__all__ = ["DOMAINS", "DomainSpec", "ToolError", "ToolSpec", "Violation", "tool_exchanges"]
