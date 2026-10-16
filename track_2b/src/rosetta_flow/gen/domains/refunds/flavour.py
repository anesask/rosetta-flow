"""Refunds flavour of the generic LLM injectors: what an invented fact or a leak sounds like here."""

from __future__ import annotations

import random

from rosetta_flow.gen.names import NAMES


def invented_fact(rng: random.Random, taken: set[float]) -> tuple[str, str]:
    amount = next(a for a in (4.90, 6.50, 9.90, 12.00, 14.50, 19.90) if a not in taken)
    hours = next(h for h in (24, 36, 48, 72) if float(h) not in taken)
    return rng.choice(
        [
            (f"a processing fee of CHF {amount:.2f} applies", f"{amount:.2f}"),
            (f"the customer will additionally get a CHF {amount:.2f} discount on their next order", f"{amount:.2f}"),
            (f"the matter will be settled within {hours} hours", str(hours)),
        ]
    )


def leak(rng: random.Random) -> tuple[str, str, str]:
    first, last = rng.choice(NAMES[rng.choice(list(NAMES))][0]), rng.choice(NAMES["de"][1])
    email = f"{first.lower()}.{last.lower()}{rng.randint(10, 99)}@mail.example".translate(str.maketrans("éèàç", "eeac"))
    order = f"A-{rng.randint(1000, 9999)}"
    aside = f"another customer, {first} {last} ({email}), had the same problem with order {order}"
    return aside, email, f"{first} {last}, {email}, {order}"
