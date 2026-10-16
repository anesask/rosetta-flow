"""The trace-as-repo view the auditor works on: an index of spans, full reads and grep."""

from __future__ import annotations

import json
import re
import secrets
import time
import unicodedata
from dataclasses import dataclass

import regex as safe_re  # re with a timeout; search patterns come from the model

from rosetta_flow.trace.models import Span, SpanKind, Trace

PREVIEW_CHARS = 80
SNIPPET_RADIUS = 40
MAX_MATCH_CHARS = 200  # a greedy pattern can match a whole 200 kB result; snippets stay small
SEARCH_TIMEOUT_S = 1.0
MAX_PATTERN_CHARS = 200
# Shorter quotes ("CHF", "false") occur in almost every span and would "verify" anything.
MIN_QUOTE_CHARS = 8
# Bounds on what one tool result may put into the auditor's context, whatever the size of the input trace.
MAX_SPAN_CHARS = 6000
MAX_POLICY_CHARS = 20_000
LIST_PAGE = 150

_NOT_IDENT = re.compile(r"[^A-Za-z0-9_.:-]")
_ELLIPSIS = re.compile(r"\s*(?:\.\.\.|…)\s*")
_SPAN_NUMBER = re.compile(r"\d+")
_SPAN_NAMED = re.compile(r"(?:span|#)\s*#?\s*(\d+)", re.IGNORECASE)
# Quote marks and JSON punctuation models drop or swap when quoting ("eligible": false vs eligible: false), and
# the data-fence characters, which the auditor sees escaped as ‹‹‹ ››› (harness/tools.py as_data).
_LOOSE_DROP = str.maketrans({c: " " for c in "\"'„“”«»‘’`{}[],:<>‹›"})
# JSON escapes in rendered tool results: a faithful quote of an e-mail inside a result has real quotes and breaks.
_JSON_ESCAPES = re.compile(r"\\[nrt\"\\/]")


class SearchError(ValueError):
    """Bad search request from the auditor; the harness reports it back as a tool error."""


def render_span(span: Span) -> str:
    """Span body as the auditor sees it. read_span, search and evidence checks must all use this one rendering."""
    match span.kind:
        case SpanKind.TOOL_CALL:
            return f"{span.tool}({_json(span.args or {})})"
        case SpanKind.TOOL_RESULT:
            return span.result if isinstance(span.result, str) else _json(span.result)
        case _:
            return span.text or ""


def normalize(text: str) -> str:
    """NFC + collapsed whitespace, so quotes survive line wrapping and composed/decomposed umlauts."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def _loose(text: str) -> str:
    # Format characters (zero-width spaces, bidi overrides) are invisible, so they must not decide a match.
    visible = "".join(ch for ch in unicodedata.normalize("NFC", text) if unicodedata.category(ch) != "Cf")
    return " ".join(visible.casefold().translate(_LOOSE_DROP).split())


def normalize_span_id(raw: object) -> str:
    """Accept what models actually send: 5, "5", "005", "span 005", "#005", "trace_0042 span 5". Ambiguous
    strings ("005-006", "0042 5"), negative numbers and numbers above 999 are no span id."""
    if isinstance(raw, bool) or (isinstance(raw, int | float) and (raw < 0 or raw != int(raw))):
        raise KeyError(raw)
    text = str(int(raw)) if isinstance(raw, int | float) else str(raw)
    named = _SPAN_NAMED.findall(text)
    numbers = named if named else _SPAN_NUMBER.findall(text)
    if len(numbers) != 1 or "-" in text.replace(" ", "")[:1] or int(numbers[0]) > 999:
        raise KeyError(raw)
    return f"{int(numbers[0]):03d}"


def _ident(value: str) -> str:
    """Tool names and call ids come from the trace but sit in the harness's own header line, outside the data
    fence: only identifier characters survive, so they cannot carry a sentence or a forged marker."""
    return _NOT_IDENT.sub("", value)[:64] or "?"


def _clip(text: str, limit: int, hint: str) -> str:
    return text if len(text) <= limit else f"{text[:limit]}\n[truncated: {len(text) - limit} more characters; {hint}]"


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


@dataclass(frozen=True)
class SearchHit:
    span_id: str
    snippet: str


class TraceRepo:
    def __init__(self, trace: Trace, policy: str) -> None:
        self.trace = trace
        self.policy = policy
        self._bodies = {s.id: render_span(s) for s in trace.spans}
        # Tag of the data fence around everything this trace puts into the auditor's context (harness/tools.py).
        self.fence = secrets.token_hex(3)

    def list_spans(self, offset: int = 0) -> str:
        t = self.trace
        start = min(max(0, offset), len(t.spans))
        end = min(start + LIST_PAGE, len(t.spans))
        lines = [f"trace {t.trace_id} ({t.domain}, {t.language}), {len(t.spans)} spans"]
        for s in t.spans[start:end]:
            label = f"{s.kind}:{s.tool}" if s.kind is SpanKind.TOOL_CALL else str(s.kind)
            if s.kind is SpanKind.TOOL_RESULT:
                label += f" [{s.status}]"
            preview = " ".join(self._bodies[s.id].split())
            if len(preview) > PREVIEW_CHARS:
                preview = preview[: PREVIEW_CHARS - 3] + "..."
            lines.append(f"{s.id}  {label:<36} {preview}")
        if end < len(t.spans):
            lines.append(f"... {len(t.spans) - end} more spans: call list_spans with offset {end}")
        return "\n".join(lines)

    def read_span(self, span_id: object) -> str:
        span = self.trace.span(normalize_span_id(span_id))
        header = [f"span {span.id}", str(span.kind)]
        if span.tool:
            header.append(f"tool {_ident(span.tool)}")
        if span.call_id:
            header.append(f"call {_ident(span.call_id)}")
        if span.status:
            header.append(f"status {span.status}")
        body = _clip(self._bodies[span.id], MAX_SPAN_CHARS, "use search to find specific text in this span")
        return " | ".join(header) + "\n" + body

    def search(self, pattern: str, regex: bool = False, max_hits: int = 20) -> list[SearchHit]:
        """Case-insensitive; one hit per span with a snippet around the first match."""
        if not isinstance(pattern, str) or not pattern.strip():
            raise SearchError("search pattern is empty")
        if len(pattern) > MAX_PATTERN_CHARS:
            raise SearchError(f"search pattern longer than {MAX_PATTERN_CHARS} characters")
        try:
            rx = safe_re.compile(pattern if regex else safe_re.escape(pattern), safe_re.IGNORECASE)
        except safe_re.error as e:
            raise SearchError(f"invalid regex: {e}") from e
        # Shape checks cannot catch every catastrophic pattern ((a|a)*$, .*.*.*x): a time limit on the whole
        # search does, and it releases the worker instead of hanging the batch.
        deadline = time.monotonic() + SEARCH_TIMEOUT_S
        hits = []
        for span_id, body in self._bodies.items():
            try:
                m = rx.search(body, timeout=max(0.01, deadline - time.monotonic()))
            except TimeoutError as e:
                raise SearchError("search took too long; use a simpler pattern or plain text") from e
            if not m:
                continue
            end_of_match = min(m.end(), m.start() + MAX_MATCH_CHARS)
            start, end = max(0, m.start() - SNIPPET_RADIUS), min(len(body), end_of_match + SNIPPET_RADIUS)
            snippet = ("..." if start else "") + " ".join(body[start:end].split()) + ("..." if end < len(body) else "")
            hits.append(SearchHit(span_id, snippet))
            if len(hits) >= max(1, max_hits):
                break
        return hits

    def read_policy(self) -> str:
        return _clip(self.policy, MAX_POLICY_CHARS, "policy is longer than the auditor may read at once")

    def contains(self, span_id: object, quote: str) -> bool:
        """Evidence check: does the quote appear in that span?

        Tolerates what models do when quoting faithfully: whitespace and Unicode form changes, dropped or swapped
        quote marks and JSON punctuation, case, and "..." between quoted fragments (fragments must keep their order).
        """
        try:
            body = self._bodies.get(normalize_span_id(span_id))
        except KeyError:
            return False
        if body is None or not isinstance(quote, str):
            return False
        fragments = [_loose(p) for p in _ELLIPSIS.split(quote) if p.strip()]
        if not fragments:
            return False
        # Every fragment must prove something on its own: "the ... and ... for" would match almost any span.
        whole = len(fragments) == 1 and fragments[0] == _loose(body)
        if not whole and any(len(f.replace(" ", "")) < MIN_QUOTE_CHARS for f in fragments):
            return False
        # The loose form is a superset of exact matching, so one pass covers both; the second rendering accepts
        # quotes of strings inside JSON results the way the model decoded them (real quotes and line breaks).
        unescaped = _JSON_ESCAPES.sub(lambda m: " " if m.group()[1] in "nrt" else m.group()[1], body)
        return any(_in_order(_loose(b), fragments) for b in {body, unescaped})


def _in_order(haystack: str, needles: list[str]) -> bool:
    pos = 0
    for needle in needles:
        if not needle:
            continue
        i = haystack.find(needle, pos)
        if i < 0:
            return False
        pos = i + len(needle)
    return True
