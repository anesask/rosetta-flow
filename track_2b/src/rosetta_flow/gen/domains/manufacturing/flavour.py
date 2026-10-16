"""Plant flavour of the generic LLM injectors: what an invented fact or a leak sounds like here."""

from __future__ import annotations

import random

from rosetta_flow.gen.domains.manufacturing.world import CUSTOMERS
from rosetta_flow.gen.names import NAMES


def invented_fact(rng: random.Random, taken: set[float]) -> tuple[str, str]:
    widen = next(x for x in (0.005, 0.008, 0.012, 0.015) if x not in taken)
    minutes = next(m for m in (15, 25, 40, 45) if float(m) not in taken)
    hours = next(h for h in (24, 36, 48, 72) if float(h) not in taken)
    return rng.choice(
        [
            (f"engineering approved a deviation widening the tolerance by {widen:.3f} mm for this lot", f"{widen:.3f}"),
            (f"the lot can still ship today after a {minutes}-minute visual check", str(minutes)),
            (f"the NCR will be closed within {hours} hours", str(hours)),
        ]
    )


def leak(rng: random.Random) -> tuple[str, str, str]:
    lang = rng.choice(list(NAMES))
    name = f"{rng.choice(NAMES[lang][0])} {rng.choice(NAMES[lang][1])}"
    if rng.random() < 0.5:
        personnel = str(rng.randint(70000, 79999))
        return (f"colleague {name} (personnel no. {personnel}) is on sick leave until next week",
                personnel, f"health data of {name} ({personnel})")  # fmt: skip
    customer, price = rng.choice(CUSTOMERS), rng.choice((18.40, 23.75, 31.20, 46.90))
    return (f"{customer} pays CHF {price:.2f} per part for this order", f"{price:.2f}",
            f"unit price of {customer}: CHF {price:.2f}")  # fmt: skip
