"""Scripted agent: code takes every action the policy requires, the LLM only writes the words.

Why: a free-running LLM agent breaks policy in ways no rule checker sees (it "confirmed" refunds it never issued),
so its "clean" traces carry hidden errors and corrupt the labels. Here a per-domain dialogue manager decides each
tool call and what each message must convey; the LLM reads the customer (typed, schema-constrained) and writes
the agent's messages. Every draft is verified (numbers come from the facts, right language, no rule break) and
rewritten with feedback, so a kept trace is clean by construction rather than by assumption.
"""

from __future__ import annotations

import json
import random
import re
from collections.abc import Callable
from typing import Any, ClassVar

from pydantic import BaseModel, ValidationError

from rosetta_flow.gen.domains.base import DomainSpec, Scenario
from rosetta_flow.gen.lang import LANGUAGE_NAMES, guess_language
from rosetta_flow.gen.names import NAMES
from rosetta_flow.gen.numbers import allowed_numbers, unsupported_numbers
from rosetta_flow.llm import LLMContext
from rosetta_flow.trace import Span, SpanKind, Trace

PERSONAS = (
    "concise and professional",
    "warm and empathetic, acknowledges the other person's concern",
    "formal and precise",
    "friendly and slightly informal",
)
MAX_DRAFTS = 4
TRANSIENT_FAILURE_RATE = 0.06
TRANSIENT_ERROR = "timeout: backend did not respond within 5 s, please retry"

_ID = re.compile(r"\b[A-Z]{1,3}-\d{2,6}\b")
_GREETING = re.compile(
    r"^\s*(hallo|hello|hi|hey|ciao|salve|salut|bonjour|bonsoir|buongiorno|buonasera|guten (tag|morgen|abend)|"
    r"grüezi|gruezi|good (morning|afternoon|evening)|dear)\b",
    re.IGNORECASE,
)
_TITLES = r"Madame|Monsieur|Mademoiselle|Herr|Frau|Signora|Signore|Signor|Sig\.ra|Sig\.|Mr\.?|Mrs\.?|Ms\.?|Dear"
_SALUTATION = re.compile(
    r"^\s*(?i:hallo|hello|hi|hey|ciao|salve|bonjour|bonsoir|buongiorno|buonasera|guten (?:tag|morgen|abend)|"
    rf"grüezi|good (?:morning|afternoon|evening)|dear)\s*,?\s+(?P<title>(?i:{_TITLES}))?\s*"
    r"(?P<name>[A-ZÄÖÜÉÈ][a-zäöüéèàçì]+(?:\s[A-ZÄÖÜÉÈ][a-zäöüéèàçì]+)?)?\s*[,!.]"
)
_SIGN_OFF = re.compile(
    r"\b(best regards|kind regards|regards,|freundliche grü(ss|ß)e|mit freundlichen|cordialement|bien à vous|"
    r"distinti saluti|cordiali saluti)|quality assistant\s*$",
    re.IGNORECASE,
)
# Claims of handing something on. Only true when a tool did it, which the agent passes on as one of these facts.
_HANDOVER = re.compile(
    r"\b(weiter(ge)?(leit|geb|gegeben|geleitet)\w*|informier\w*|benachrichtig\w*|transm[ei]\w*|transf[ée]r\w*|"
    r"inoltrat\w*|inoltr\w*|notificat\w*|segnalat\w*|forward\w*|passed (it )?on|notified|informed)\b",
    re.IGNORECASE,
)
HANDOVER_FACTS = {"ticket_id", "disposition_decided_by", "task_id", "first_article_task_id", "tool_changes"}
_FIRST_NAMES = frozenset(n for firsts, _ in NAMES.values() for n in firsts)
_GREETING_LANG = {
    "guten": "de", "grüezi": "de", "gruezi": "de", "hallo": "de", "bonjour": "fr", "bonsoir": "fr", "salut": "fr",
    "buongiorno": "it", "buonasera": "it", "salve": "it", "ciao": "it", "hello": "en", "hi": "en", "hey": "en",
    "good": "en", "dear": "en",
}  # fmt: skip
# Informal address the 70B slips into with "friendly" personas; Swiss support writes Sie / vous / Lei.
_INFORMAL = {
    "de": re.compile(r"\b(du|dich|dir|dein\w*)\b", re.IGNORECASE),
    "fr": re.compile(r"\b(tu|toi|ton|ta|tes|t'as)\b|\bsalut\b", re.IGNORECASE),
    "it": re.compile(r"\b(ti|tuo|tua|tuoi|tue)\b|\bciao\b", re.IGNORECASE),
}


_DASHES = str.maketrans(dict.fromkeys("‐‑‒–—−", "-"))


def plain_dashes(text: str) -> str:
    """The 70B writes ids with non-breaking hyphens (WO‑24017); id regexes expect ASCII ones."""
    return text.translate(_DASHES)


class VerbalizationError(RuntimeError):
    """No draft passed verification; the run is dropped rather than kept with a possibly wrong message."""


def strip_greeting(text: str) -> str:
    """Drop a leading greeting and a name or title right after it ("Guten Tag, Sarah Schmid."), nothing else."""
    m = _GREETING.match(text)
    if not m:
        return text
    rest = text[m.end() :].lstrip(" ,!.")
    rest = re.sub(rf"^(?:(?i:{_TITLES})\s+)?[A-ZÄÖÜÉÈ][\w'-]+(?:\s[A-ZÄÖÜÉÈ][\w'-]+)?\s*[.!?,]\s*", "", rest, count=1)
    return rest[:1].upper() + rest[1:] if rest else text


class ScriptedAgent:
    """Base class: records tool calls, internal notes and verified messages as spans of the running trace."""

    NOTES: ClassVar[dict[str, tuple[str, ...]]] = {}

    def __init__(
        self,
        spec: DomainSpec,
        world: Any,
        scenario: Scenario,
        spans: list[Span],
        ctx: LLMContext,
        rng: random.Random,
        clock: Callable[[], int] = lambda: 0,
    ) -> None:
        self.spec, self.world, self.scenario, self.spans, self.ctx, self.rng = spec, world, scenario, spans, ctx, rng
        self.clock = clock
        self.persona = rng.choice(PERSONAS)
        self.n_calls = 0
        self.messages_sent = 0
        # Facts behind already accepted messages: the agent may repeat what it verifiably said before.
        self.stated_facts: list[dict[str, Any]] = []

    # building blocks

    def _span(self, start_ms: int | None = None, **kw: Any) -> Span:
        now = self.clock()
        start = now if start_ms is None else start_ms
        span = Span(id=f"{len(self.spans):03d}", start_ms=start, end_ms=max(start, now), **kw)
        self.spans.append(span)
        return span

    def tool(self, name: str, **args: Any) -> tuple[str, Any]:
        """Call a tool. Read-only lookups sometimes time out once; the agent retries like a real one would."""
        if name.startswith("get_") and self.rng.random() < TRANSIENT_FAILURE_RATE:
            self.ctx.usage.transient_failures += 1
            self._record(name, args, "error", TRANSIENT_ERROR)
            self.note("retry", tool=name)
        status, result = self.spec.call(self.world, name, args)
        self._record(name, args, status, result)
        return status, result

    def _record(self, name: str, args: dict[str, Any], status: str, result: Any) -> None:
        self.n_calls += 1
        call_id = f"c{self.n_calls}"
        self._span(kind=SpanKind.TOOL_CALL, tool=name, args=args, call_id=call_id)
        self._span(kind=SpanKind.TOOL_RESULT, call_id=call_id, status=status, result=result)

    def note(self, key: str, p: float = 0.55, **fmt: Any) -> None:
        """Short internal reasoning note, the way real agents interleave thinking with tool calls."""
        options = self.NOTES.get(key) or _GENERIC_NOTES.get(key)
        if options and self.rng.random() < p:
            self._span(kind=SpanKind.LLM_REASONING, text=self.rng.choice(options).format(**fmt))

    def history(self, last: int = 6) -> list[tuple[str, str]]:
        talk = [s for s in self.spans if s.kind in (SpanKind.USER_MESSAGE, SpanKind.AGENT_MESSAGE)]
        role = self.spec.user_role
        return [(role if s.kind is SpanKind.USER_MESSAGE else "agent", s.text or "") for s in talk[-last:]]

    def say(self, intent: str, **facts: Any) -> str:
        """Write, verify and record one agent message conveying `intent` using only `facts`."""
        lang = self.scenario.language
        feedback: list[str] = []
        started = self.clock()
        draft = ""
        for _ in range(MAX_DRAFTS):
            draft = self.ctx.complete(self._verbalizer_prompt(intent, facts, feedback), temperature=0.7, max_tokens=300)
            draft = re.sub(r"\s*\n+\s*", " ", draft.strip())  # content-neutral: the 70B lays chats out as letters
            if self.messages_sent:
                draft = strip_greeting(draft)  # content-neutral repair; the 70B greets on every turn otherwise
            problems = self.verify(draft, facts, lang)
            if not problems:
                self._span(start_ms=started, kind=SpanKind.AGENT_MESSAGE, text=draft)
                self.messages_sent += 1
                self.stated_facts.append(facts)
                return draft
            self.ctx.usage.rejected_drafts += 1
            feedback = problems
        raise VerbalizationError(f"no valid draft for '{intent}': {feedback}; last draft: {draft[:200]!r}")

    def verify(self, draft: str, facts: dict[str, Any], lang: str) -> list[str]:
        problems = []
        if not draft or len(draft) > 900:
            problems.append("the message must be 1 to 4 sentences")
        if re.search(r"\[[^\]]{2,40}\]", draft):
            problems.append("no placeholders in square brackets: write a real sentence or leave it out")
        if "\n" in draft.strip() or _SIGN_OFF.search(draft):
            problems.append("one short chat paragraph: no line breaks, no letter-style sign-off or signature")
        if "**" in draft or "](" in draft or re.search(r"^\s*([-*•]|\d+\.)\s", draft, re.MULTILINE):
            problems.append("plain text only: no markdown, no links in brackets, no lists")
        handed_over = HANDOVER_FACTS & {k for f in (facts, *self.stated_facts) for k in f}  # also said earlier
        if _HANDOVER.search(draft) and not handed_over:
            problems.append("do not say you forwarded, passed on or notified anything: no tool did that")
        if invented := self._invented_address(draft):
            problems.append(f"do not address the {self.spec.user_role} as '{invented}': use no name or title")
        if self.messages_sent and _GREETING.match(draft):
            problems.append("no greeting: the conversation is already under way")
        if informal := _INFORMAL.get(lang, re.compile(r"$^")).search(draft):
            problems.append(f"address the {self.spec.user_role} formally, never with '{informal.group()}'")
        usable = [facts, *self.stated_facts, self._known_ids()]
        if bad := unsupported_numbers(draft, usable):
            exact = sorted(allowed_numbers(usable) - {float(int(x)) for x in range(1, 32)})[:12]
            problems.append(
                f"these numbers are not in the facts and must not appear: {bad}. Never round or compute amounts; "
                f"copy them exactly as given (allowed values include {exact})"
            )
        guessed = guess_language(draft)
        if guessed is not None and guessed != lang:
            problems.append(f"write in {LANGUAGE_NAMES[lang]}, not {LANGUAGE_NAMES[guessed]}")
        else:
            # A single foreign sentence or greeting ("Guten Tag." in an English reply) passes the whole-text guess.
            first = (re.match(r"\s*([^\W\d_]+)", draft) or [None, ""])[1].lower()
            foreign = [_GREETING_LANG[first]] if _GREETING_LANG.get(first, lang) != lang else []
            foreign += [g for x in re.split(r"(?<=[.!?])\s+", draft) if (g := guess_language(x, 2)) not in (None, lang)]
            if foreign:
                problems.append(f"every sentence, greeting included, must be in {LANGUAGE_NAMES[lang]}")
        candidate_id = f"{len(self.spans):03d}"
        probe = Trace(
            trace_id="probe",
            domain=self.spec.domain,
            language=lang,
            agent=self.spec.agent,
            policy_id=self.spec.policy_id,
            spans=[*self.spans, Span(id=candidate_id, kind=SpanKind.AGENT_MESSAGE, text=draft)],
        )
        for v in self.spec.check(probe, self.world):
            if candidate_id in v.span_ids:
                problems.append(f"policy problem: {v.detail}")
        return problems

    def _invented_address(self, draft: str) -> str | None:
        """A name or title the requester never wrote: in the salutation ("Hi Thomas", "Bonjour Madame") or
        anywhere else as a known first name ("Thank you, Anna.")."""
        written = " ".join(s.text or "" for s in self.spans if s.kind is SpanKind.USER_MESSAGE)
        words = re.findall(r"\b[A-Z][a-zéèàçë]+\b", draft)
        if stray := next((w for w in words if w in _FIRST_NAMES and w not in written), None):
            return stray
        m = _SALUTATION.match(draft)
        if not m:
            return None
        title, name = m.group("title"), m.group("name")
        if name and name not in written:
            return " ".join(filter(None, [title, name]))
        if title and not name:
            return title
        return None

    def _known_ids(self) -> list[str]:
        """Order, customer and ticket ids already in the conversation: referring to them is never invented."""
        ids = {self.scenario.customer_id}
        for s in self.spans:
            raw = " ".join(filter(None, [s.text, json.dumps(s.args or {}), json.dumps(s.result)]))
            ids.update(_ID.findall(plain_dashes(raw)))
        return sorted(ids)

    def _verbalizer_prompt(self, intent: str, facts: dict[str, Any], feedback: list[str]) -> list[dict[str, Any]]:
        convo = "\n".join(f"{who}: {text}" for who, text in self.history()) or "(no messages yet)"
        first = self.messages_sent == 0
        system = (
            f"You write the next chat message of this agent: {self.spec.agent.description}\n"
            f"Language: {LANGUAGE_NAMES[self.scenario.language]}. Style: {self.persona}.\n"
            "Rules: 1 to 4 sentences, plain text, no markdown or lists. "
            f"Address the {self.spec.user_role} formally (German Sie, French vous, Italian Lei), as Swiss firms do. "
            + ("Start with a short greeting. " if first else "No greeting. ")
            + "Use a person's name only if they wrote it themselves, and never guess gender (no Madame, Herr, "
            "Signora without the name they gave). "
            "Convey exactly the content below. Use only the facts given: no other numbers, dates, fees, "
            "deadlines or promises. Never claim an action happened unless the facts say so, never confirm what the "
            "other person says they did, and never announce your own next steps (forwarding, notifying, calling "
            "back) unless the facts list them. "
            "Output only the message text." + self._terminology(intent, facts)
        )
        user = (
            f"Conversation so far:\n{convo}\n\n"
            f"Content to convey: {intent}\n"
            f"Facts you may use:\n{json.dumps(facts, ensure_ascii=False, indent=1)}"
        )
        if feedback:
            user += "\n\nYour previous draft was rejected. Fix this:\n- " + "\n- ".join(feedback)
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def _terminology(self, intent: str, facts: dict[str, Any]) -> str:
        # Only terms this message needs: listing all of them made the 70B mention a first-article check in a
        # re-measurement reply.
        about = (intent + json.dumps(facts, ensure_ascii=False)).lower()
        terms = [entry for trigger, entry in self.spec.glossary.items() if trigger in about]
        return "\nTerminology: " + "; ".join(terms) if terms else ""

    def read[M: BaseModel](self, schema: type[M], instruction: str, text: str) -> M | None:
        """Typed reading of a customer message via JSON-schema output; None if the model cannot comply."""
        messages = [
            {"role": "system", "content": instruction},
            {"role": "user", "content": f"Conversation so far:\n{self._convo()}\n\nLatest message:\n{text}"},
        ]
        fmt = {"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()}}
        for _ in range(2):
            raw = self.ctx.complete(messages, temperature=0, max_tokens=200, response_format=fmt)
            try:
                return schema.model_validate_json(raw)
            except ValidationError:
                continue
        return None

    def _convo(self) -> str:
        return "\n".join(f"{who}: {text}" for who, text in self.history(8)) or "(none)"

    def respond(self, customer_text: str, customer_done: bool = False) -> str:
        """Handle one customer message: take the actions the policy requires, then reply."""
        raise NotImplementedError


_GENERIC_NOTES: dict[str, tuple[str, ...]] = {
    "retry": (
        "{tool} timed out, retrying once.",
        "Backend timeout on {tool}; trying again before telling the customer anything.",
        "Transient error from {tool}. Retry.",
    ),
}
