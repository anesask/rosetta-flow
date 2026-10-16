"""Numbers as they appear in Swiss multilingual text: 1'258.90, 1’258,90, 129,90, 05.10.2026.

Shared by the verbaliser (no invented numbers in agent messages) and the error injectors (change one number,
keep its written style), so both read and write numbers the same way.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date
from typing import Any

NUMBER = re.compile(r"(?<![\w.])\d{1,3}(?:['’]\d{3})+(?:[.,]\d+)?|(?<![\w.])\d+(?:[.,]\d+)?")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
# Dates written the European way (05.10.2026, 5/10/26) are read by their parts, not as decimals.
WRITTEN_DATE = re.compile(r"(?<![\w.])(\d{1,2})[./](\d{1,2})[./](\d{2,4})(?![\w])")
_TOKEN_PARTS = re.compile(r"(\d{1,3}(?:['’]\d{3})+|\d+)(?:([.,])(\d+))?")


# Values are compared exactly at this many decimals: measurements have three, so rounding to cents hid wrong
# limits and measured values in messages that were then labelled clean.
PRECISION = 6
_ID_PREFIX = re.compile(r"[A-Za-z][-‐‑]$")


def inside_identifier(text: str, m: re.Match[str]) -> bool:
    """Digits of an id like MC-03 or WO-24017: numbers to verify, but never a value an injector may change."""
    return bool(_ID_PREFIX.search(text[max(0, m.start() - 2) : m.start()]))


def numbers_in(text: str) -> list[str]:
    return NUMBER.findall(text)


def as_float(token: str) -> float | None:
    try:
        return float(token.replace("'", "").replace("’", "").replace(",", "."))
    except ValueError:
        return None


def number_tokens(text: str) -> Iterator[re.Match[str]]:
    """Number tokens outside written dates, with positions (for in-place replacement)."""
    dates = [m.span() for m in WRITTEN_DATE.finditer(text)]
    for m in NUMBER.finditer(text):
        if not any(a <= m.start() < b for a, b in dates):
            yield m


def number_values(text: str) -> set[float]:
    """All numeric values a text states, with written dates split into day, month and year."""
    out = {round(f, PRECISION) for m in number_tokens(text) if (f := as_float(m.group())) is not None}
    for m in WRITTEN_DATE.finditer(text):
        year = int(m.group(3))
        out |= {float(int(m.group(1))), float(int(m.group(2))), float(year + 2000 if year < 100 else year)}
    return out


def format_like(token: str, value: float) -> str:
    """Write `value` in the style of `token`: same decimals, decimal mark and thousands separator."""
    m = _TOKEN_PARTS.fullmatch(token)
    if m is None:
        return f"{value:.2f}"
    int_part, sep, frac = m.groups()
    thousands = next((c for c in "'’" if c in int_part), "")
    decimals = len(frac) if frac else 0
    whole, _, fraction = f"{value:.{decimals}f}".partition(".")
    if thousands:
        whole = f"{int(whole):,}".replace(",", thousands)
    return whole + (f"{sep}{fraction}" if decimals else "")


def allowed_numbers(facts: Any) -> set[float]:
    """Every number a message may mention: numeric facts, digits inside ids, and the parts of ISO dates."""
    out: set[float] = set()

    def walk(v: Any) -> None:
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, int | float):
            out.add(round(float(v), PRECISION))
        elif isinstance(v, str):
            if m := _ISO_DATE.match(v):
                out.update(float(x) for x in m.groups())
            for tok in numbers_in(v):
                if (f := as_float(tok)) is not None:
                    out.add(round(f, PRECISION))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list | tuple | set):
            for x in v:
                walk(x)
        elif isinstance(v, date):
            walk(v.isoformat())

    walk(facts)
    return out


def unsupported_numbers(text: str, facts: Any) -> list[str]:
    allowed = allowed_numbers(facts)
    for m in WRITTEN_DATE.finditer(text):
        year = int(m.group(3))
        allowed_year = year + 2000 if year < 100 else year
        if not {float(int(m.group(1))), float(int(m.group(2))), float(allowed_year)} <= allowed:
            return [m.group()]
    bad = []
    for m in number_tokens(text):
        f = as_float(m.group())
        # Exact, not within a cent: 12.02 for a limit of 12.018 is a different (and wrong) limit.
        if f is None or round(f, PRECISION) not in allowed:
            bad.append(m.group())
    return bad
