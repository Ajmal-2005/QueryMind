"""Business glossary (F24).

"Active user" is not in any schema. It is a definition an organisation holds
in its head, and a model asked to compute it will invent one - a different one
each time, all of them plausible, none of them the company's. The glossary is
where that definition gets written down once.

Matching is deliberately literal: a term is used when its words appear in the
question. Embedding similarity would be the fancier choice and the wrong one -
a glossary entry silently applied because it was *nearly* relevant would
change the meaning of a query without the user asking, and they would have no
way to see why the number moved.
"""

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.learning import GlossaryTerm

log = get_logger(__name__)

MAX_TERMS_IN_PROMPT = 8


@dataclass
class MatchedTerm:
    term: str
    definition: str
    sql_expression: str | None


def _pattern(term: str) -> re.Pattern[str]:
    """Word-boundary match on the whole phrase, whitespace-insensitive.

    `\\s+` between words so "active user" matches "active  users" and
    "Active User"; `s?` on the tail so a plural does not miss.
    """
    words = [re.escape(w) for w in term.strip().split()]
    return re.compile(r"\b" + r"\s+".join(words) + r"s?\b", re.IGNORECASE)


def match(db: Session, connection_id: str, question: str) -> list[MatchedTerm]:
    """Glossary entries whose term appears in this question."""
    terms = db.scalars(
        select(GlossaryTerm).where(GlossaryTerm.connection_id == connection_id)
    ).all()

    matched = [
        MatchedTerm(
            term=entry.term,
            definition=entry.definition,
            sql_expression=entry.sql_expression,
        )
        for entry in terms
        if _pattern(entry.term).search(question)
    ]

    # Longest term first: when both "user" and "active user" are defined, the
    # more specific definition is the one that should lead.
    matched.sort(key=lambda m: len(m.term), reverse=True)

    if matched:
        log.info(
            "glossary_matched",
            connection_id=connection_id,
            terms=[m.term for m in matched],
        )
    return matched[:MAX_TERMS_IN_PROMPT]


def render(matched: list[MatchedTerm]) -> str:
    """The glossary section of the prompt."""
    if not matched:
        return ""

    lines = [
        "These business terms appear in the question and have agreed "
        "definitions. Use them exactly; do not substitute your own.",
        "",
    ]
    for entry in matched:
        lines.append(f"- **{entry.term}**: {entry.definition}")
        if entry.sql_expression:
            lines.append(f"  SQL: `{entry.sql_expression}`")
    return "\n".join(lines)


__all__ = ["MatchedTerm", "match", "render"]
