"""Stopword language guess for de/fr/it/en. Good enough to flag replies in the wrong language, nothing more."""

from __future__ import annotations

import re

from rosetta_flow.trace import Language

_STOPWORDS: dict[Language, frozenset[str]] = {
    "de": frozenset(
        "der die das und ist nicht ich sie wir ihr ihre ihnen mit für auf ein eine einen den dem zu von "
        "wurde werden haben hat bitte danke leider gerne".split()
    ),
    "fr": frozenset(
        "le la les et est pas je vous nous votre vos avec pour sur un une des du de au été être avons "
        "merci malheureusement bien".split()
    ),
    "it": frozenset(
        "il lo la gli le e è non io lei noi suo sua con per su un una dei del di al stato essere "
        "grazie purtroppo".split()
    ),
    "en": frozenset(
        "the and is not i you we your with for on a an of to was been be have has please thank unfortunately".split()
    ),
}

LANGUAGE_NAMES: dict[Language, str] = {"de": "Swiss Standard German", "fr": "French", "it": "Italian", "en": "English"}

_WORD = re.compile(r"[a-zàâäçéèêëîïôöùûüœ]+", re.IGNORECASE)


def guess_language(text: str, min_hits: int = 3) -> Language | None:
    """None when the text is too short or ambiguous to call; callers must treat None as 'unknown', not 'wrong'."""
    words = [w.lower() for w in _WORD.findall(text)]
    scores = {lang: sum(w in sw for w in words) for lang, sw in _STOPWORDS.items()}
    best = max(scores, key=lambda lang: scores[lang])
    ranked = sorted(scores.values(), reverse=True)
    if ranked[0] < min_hits or ranked[0] < 2 * ranked[1]:
        return None
    return best
