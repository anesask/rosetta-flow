"""LLM access. Configuration comes only from LLM_NAME, LLM_BASE_URL and LLM_API_KEY."""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from json_repair import repair_json
from openai import OpenAI

REQUIRED_VARS = ("LLM_NAME", "LLM_BASE_URL", "LLM_API_KEY")

# CHF per million tokens, input and output blended, derived from the CSCS usage dashboard on 7 Oct 2026
# (70B: CHF 0.7290 for 7.9M tokens; 8B: CHF 0.0670 for 5.5M). Cached tokens are billed like uncached ones.
PRICE_CHF_PER_M_TOKENS = {"swiss-ai/Apertus-v1.5-70B": 0.0923, "swiss-ai/Apertus-v1.5-8B": 0.0122}


def cost_chf(model: str, tokens: int) -> float | None:
    """Estimated CHF for `tokens` tokens on `model`; None for models without a known price."""
    price = PRICE_CHF_PER_M_TOKENS.get(model)
    return None if price is None else round(tokens * price / 1e6, 4)


@dataclass(frozen=True)
class LLMConfig:
    name: str
    base_url: str
    api_key: str = field(repr=False)

    @classmethod
    def from_env(cls) -> LLMConfig:
        missing = [v for v in REQUIRED_VARS if not os.environ.get(v)]
        if missing:
            raise RuntimeError(f"Missing env vars: {', '.join(missing)} (see .env.example)")
        return cls(
            name=os.environ["LLM_NAME"],
            base_url=os.environ["LLM_BASE_URL"].rstrip("/"),
            api_key=os.environ["LLM_API_KEY"],
        )


@lru_cache(maxsize=4)
def get_client(cfg: LLMConfig) -> OpenAI:
    return OpenAI(base_url=cfg.base_url, api_key=cfg.api_key, max_retries=3, timeout=300)


def chat(cfg: LLMConfig, messages: list[dict], model: str | None = None, **kwargs):
    """One chat completion. `model` overrides cfg.name (e.g. reference 70B vs on-prem 8B)."""
    return get_client(cfg).chat.completions.create(model=model or cfg.name, messages=messages, **kwargs)


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    rejected_drafts: int = 0
    transient_failures: int = 0

    def add(self, resp: Any) -> None:
        self.calls += 1
        if getattr(resp, "usage", None):
            prompt, completion = resp.usage.prompt_tokens or 0, resp.usage.completion_tokens or 0
            self.prompt_tokens += prompt
            self.completion_tokens += completion
            _count_spent(prompt + completion)


# Every token any context spends in this process, including work that later failed: token budgets read this,
# because per-record usage never sees items that raised after several calls (dropped simulations).
_spent = 0
_spent_lock = threading.Lock()


def _count_spent(tokens: int) -> None:
    global _spent
    with _spent_lock:
        _spent += tokens


def tokens_spent() -> int:
    return _spent


_KEY_LIKE = re.compile(r"\b(?:sk|key|tok)[-_][A-Za-z0-9_-]{12,}|\b[A-Za-z0-9_-]{40,}\b")


def redact(text: str) -> str:
    """Error text as it may be printed or stored: gateways sometimes echo the (masked or full) key in 401s."""
    key = os.environ.get("LLM_API_KEY", "")
    if len(key) >= 8:
        text = text.replace(key, "***")
    return _KEY_LIKE.sub("***", text)


@dataclass
class LLMContext:
    """A model plus token accounting; the single call path, so tests can replace `chat` in one place."""

    cfg: LLMConfig
    model: str | None = None
    usage: Usage = field(default_factory=Usage)

    def message(self, messages: list[dict[str, Any]], **kw: Any) -> Any:
        resp = chat(self.cfg, messages, model=self.model, **kw)
        self.usage.add(resp)
        choices = getattr(resp, "choices", None)
        if not choices:
            raise RuntimeError("model returned no choices")
        return choices[0].message

    def complete(self, messages: list[dict[str, Any]], **kw: Any) -> str:
        return (self.message(messages, **kw).content or "").strip()


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str
    recovered: bool = False  # parsed from the model's own markup in the text, not from the server's tool_calls


# Apertus' native tool-call syntax. When the server-side parser misses it, it arrives as plain text, e.g.
# <invoke name="read_policy"><parameter name="reason">...</parameter></invoke>
_INVOKE = re.compile(r'<invoke name="([^"]+)">(.*?)</invoke>', re.DOTALL)
TOOLS_PREFIX, TOOLS_SUFFIX = "<|tools_prefix|>", "<|tools_suffix|>"
_PARAMETER = re.compile(r'<parameter name="([^"]+)">(.*?)</parameter>', re.DOTALL)


def tool_calls_of(msg: Any) -> list[ToolCall]:
    """The model's tool calls with ids that are present and unique: the tool results are matched back by id, and a
    missing or repeated id makes the next request invalid. Falls back to calls written in native markup."""
    raw = [
        (getattr(tc, "id", None) or "", getattr(tc.function, "name", None) or "", tc.function.arguments or "", False)
        for tc in getattr(msg, "tool_calls", None) or []
        if getattr(tc, "function", None) is not None
    ]
    content = getattr(msg, "content", None) or ""
    if not raw:
        raw = [("", name, json.dumps(_markup_args(body), ensure_ascii=False), True)
               for name, body in _INVOKE.findall(content)]  # fmt: skip
    if not raw:
        raw = [("", name, json.dumps(args, ensure_ascii=False), True) for name, args in _prefixed_calls(content)]
    calls, seen = [], set()
    for i, (call_id, name, arguments, recovered) in enumerate(raw):
        if not call_id or call_id in seen:
            call_id = f"call_{i}_{uuid.uuid4().hex[:8]}"
        seen.add(call_id)
        calls.append(ToolCall(call_id, _clean_name(name), arguments, recovered))
    return calls


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _clean_name(name: str) -> str:
    """The tool name without leaked template tokens. The 8B sometimes writes `<|tool_output_end|><|tools_prefix|>
    [{"report` and vLLM's parser keeps all of it as the name (112 such calls in 244 dev audits, each answered
    'unknown tool' until the call limit); the real name is the last identifier."""
    if _IDENTIFIER.fullmatch(name):
        return name
    words = _IDENTIFIER.findall(name)
    return words[-1] if words else name


MAX_REPAIR_CHARS, MAX_REPAIR_BRACKETS = 20_000, 200


def loads_lenient(text: str) -> Any:
    """JSON, or a repaired reading of almost-JSON; None if neither works. The 8B often breaks its report while
    quoting JSON tool results as evidence (nested quotes, a stray bracket); the content is usually right. A repaired
    report still has to pass the schema, grounding and verbatim-evidence checks."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, RecursionError):
        pass
    # repair_json is slow on deep nesting (0.7 s for 5,000 "{"), a cheap way to stall the harness; a real report
    # has a few dozen brackets at most.
    if len(text) > MAX_REPAIR_CHARS or text.count("{") + text.count("[") > MAX_REPAIR_BRACKETS:
        return None
    try:
        value = repair_json(text, return_objects=True)
    except (ValueError, RecursionError):
        return None
    return value if isinstance(value, dict | list) and value else None


def strip_markup(content: str | None) -> str:
    text = (content or "").replace("<|inner_prefix|>", "").replace("<|inner_suffix|>", "")
    if TOOLS_PREFIX in text:
        text = text[: text.index(TOOLS_PREFIX)]
    return _INVOKE.sub("", text).strip()


def broken_prefixed_call(content: str | None) -> str | None:
    """Why a <|tools_prefix|> call in the text cannot be parsed, or None if there is none or it parses."""
    text = content or ""
    if TOOLS_PREFIX not in text or _prefixed_calls(text):
        return None
    body = text[text.index(TOOLS_PREFIX) + len(TOOLS_PREFIX) :].replace(TOOLS_SUFFIX, "").strip()
    try:
        json.JSONDecoder().raw_decode(body)
    except json.JSONDecodeError as e:
        return f"{e.msg} at character {e.pos}, near: {body[max(0, e.pos - 60) : e.pos + 20]!r}"
    except RecursionError:
        return "the arguments are nested far too deeply"
    return 'expected a list like [{"tool_name": {arguments}}]'


def _prefixed_calls(content: str) -> list[tuple[str, dict[str, Any]]]:
    """Apertus' other native format, leaked into the text by the 8B: <|tools_prefix|>[{"name": {args}}, ...]."""
    if TOOLS_PREFIX not in content:
        return []
    body = content[content.index(TOOLS_PREFIX) + len(TOOLS_PREFIX) :].replace(TOOLS_SUFFIX, "").strip()
    try:
        calls, _ = json.JSONDecoder().raw_decode(body)
    except (json.JSONDecodeError, RecursionError):  # malformed or deeply nested: try a repair first
        calls = loads_lenient(body)
        if calls is None:
            return []  # the harness answers with a parse error and the model retries
    if isinstance(calls, dict):
        calls = [calls]
    if not isinstance(calls, list):
        return []
    return [
        (name, args)
        for call in calls
        if isinstance(call, dict) and len(call) == 1
        for name, args in call.items()
        if isinstance(name, str) and isinstance(args, dict)
    ]


def _markup_args(body: str) -> dict[str, Any]:
    args: dict[str, Any] = {}
    for key, value in _PARAMETER.findall(body):
        try:
            args[key] = json.loads(value)
        except (json.JSONDecodeError, RecursionError):  # deep nesting from a looping model
            args[key] = value.strip()
    return args


def assistant_tool_message(content: str | None, calls: list[ToolCall]) -> dict[str, Any]:
    """Echo an assistant turn with tool calls back into the history in the OpenAI wire format."""
    return {
        "role": "assistant",
        "content": strip_markup(content),  # recovered markup is re-sent as real tool_calls, not twice
        "tool_calls": [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": _echo_arguments(c.arguments)}}
            for c in calls
        ],
    }


def _echo_arguments(arguments: str | None) -> str:
    # CSCS (Apertus chat template) answers 400 "Invalid tool call" to any history containing a tool call with
    # empty arguments, verified 7 Oct 2026; the model's own `{}` would otherwise kill the next request.
    return '{"reason": ""}' if not arguments or arguments.strip() in ("{}", "") else arguments
