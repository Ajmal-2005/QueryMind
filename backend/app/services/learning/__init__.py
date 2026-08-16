"""What the system learns from its users: corrections, glossary, suggestions."""

from app.services.learning.corrections import (
    Example,
    record_correction,
    similar_examples,
)
from app.services.learning.glossary import MatchedTerm
from app.services.learning.suggestions import Suggestion, suggest

__all__ = [
    "Example",
    "MatchedTerm",
    "Suggestion",
    "record_correction",
    "similar_examples",
    "suggest",
]
