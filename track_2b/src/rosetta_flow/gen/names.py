"""Fictional Swiss people names per language, shared by all simulated domains."""

from __future__ import annotations

from rosetta_flow.trace import Language

NAMES: dict[Language, tuple[list[str], list[str]]] = {
    "de": (
        ["Lukas", "Anna", "Reto", "Sandra", "Marco", "Nicole", "Thomas", "Laura", "Beat", "Sarah"],
        ["Meier", "Keller", "Brunner", "Huber", "Schmid", "Steiner", "Baumann", "Frei", "Gerber", "Widmer"],
    ),
    "fr": (
        ["Camille", "Julien", "Léa", "Nicolas", "Chloé", "Mathieu", "Sophie", "Antoine", "Manon", "Olivier"],
        ["Rochat", "Favre", "Bonvin", "Perret", "Morel", "Girard", "Dubois", "Rey", "Jaquet", "Chevalley"],
    ),
    "it": (
        ["Giulia", "Marco", "Chiara", "Luca", "Sara", "Matteo", "Elena", "Davide", "Francesca", "Andrea"],
        [
            "Bernasconi",
            "Rossi",
            "Ferrari",
            "Pedrazzini",
            "Lombardi",
            "Colombo",
            "Galli",
            "Bianchi",
            "Fontana",
            "Moretti",
        ],
    ),
    "en": (
        ["James", "Emily", "Daniel", "Olivia", "Michael", "Hannah", "Ryan", "Grace", "Adam", "Chloe"],
        ["Taylor", "Brown", "Wilson", "Clarke", "Walker", "Hughes", "Evans", "Turner", "Wright", "Hall"],
    ),
}
LANGUAGE_WEIGHTS: dict[Language, int] = {"de": 35, "fr": 25, "it": 15, "en": 25}
