"""Fake model endpoints for offline tests: customer, typed reader and verbaliser for the scripted agent."""

import json
import re
from types import SimpleNamespace as NS

ORDER = re.compile(r"A-\d{4}")
REPLIES = {
    "de": ("Swiss Standard German", "Vielen Dank für Ihre Nachricht, wir haben Ihr Anliegen für Sie geprüft."),
    "fr": ("French", "Merci pour votre message, nous avons bien vérifié votre demande pour vous."),
    "it": ("Italian", "Grazie per il suo messaggio, abbiamo verificato la sua richiesta per lei."),
    "en": ("English", "Thank you for your message, we have checked your request for you."),
}
_FACTS = re.compile(r"Facts you may use:\n(.*?)(?:\n\nYour previous draft|\Z)", re.DOTALL)


def resp(content=None, tool_calls=None):
    return NS(choices=[NS(message=NS(content=content, tool_calls=tool_calls))], usage=None)


def call(name, arguments, i=0):
    return NS(id=f"api-{i}", function=NS(name=name, arguments=arguments))


def customer(messages):
    if sum(m["role"] == "assistant" for m in messages):
        return resp("Danke, tschüss [end]")
    order = ORDER.search(messages[0]["content"])
    return resp(f"Hallo, meine Bestellung {order.group() if order else ''} ist leider kaputt angekommen.")


def _numbers(value):
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, int | float):
        return [f"{value:.2f}" if isinstance(value, float) and not value.is_integer() else str(int(value))]
    if isinstance(value, dict):
        return [n for v in value.values() for n in _numbers(v)]
    if isinstance(value, list):
        return [n for v in value for n in _numbers(v)]
    return []


def scripted_models(bad_first_draft=False, with_numbers=True):
    """Customer + reader + verbaliser. With numbers, replies state the numeric facts like a real agent would."""
    drafts = {"n": 0}

    def chat(cfg, messages, model=None, **kw):
        system = messages[0]["content"]
        if "response_format" in kw:
            order = ORDER.search(messages[-1]["content"])
            read = {"order_id": order.group() if order else None, "issue": "damaged", "wants": "refund",
                    "asks_refund_timing": False, "pushes_back": False}  # fmt: skip
            return resp(json.dumps(read))
        if system.startswith("You write the next chat message"):
            drafts["n"] += 1
            if bad_first_draft and drafts["n"] == 1:
                return resp("Wir erstatten Ihnen CHF 999 zurück, danke für Ihre Geduld.")
            lang = next(k for k, name in REPLIES.items() if f"Language: {name[0]}" in system)
            text = REPLIES[lang][1]
            if with_numbers and (m := _FACTS.search(messages[-1]["content"])):
                nums = _numbers(json.loads(m.group(1)))
                text += (" " + " / ".join(nums)) if nums else ""
            return resp(text)
        return customer(messages)

    return chat
