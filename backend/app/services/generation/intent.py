"""Intent analysis.

Classifies a question before retrieval so the rest of the pipeline knows what
shape of answer to expect, and resolves follow-ups ("break that down by
region") against the conversation so far.

Rule-based rather than an LLM call. The proposal budgets 300 ms for this
stage; a round-trip cannot meet that, and the classification is only used to
steer the prompt and the later chart choice — a wrong label degrades quality
rather than breaking correctness.
"""

import enum
import re
from dataclasses import dataclass, field


class QuestionType(str, enum.Enum):
    AGGREGATION = "aggregation"
    COMPARISON = "comparison"
    TREND = "trend"
    RANKING = "ranking"
    FILTER = "filter"
    AMBIGUOUS = "ambiguous"


# Ordered by specificity: the first pattern group that matches wins, so
# "top 5 ... last quarter" classifies as a ranking rather than a trend.
PATTERNS: list[tuple[QuestionType, tuple[str, ...]]] = [
    (
        QuestionType.RANKING,
        (
            r"\btop\b",
            r"\bbottom\b",
            r"\bbest\b",
            r"\bworst\b",
            r"\bhighest\b",
            r"\blowest\b",
            r"\brank(ed|ing)?\b",
            r"\bmost\b",
            r"\bleast\b",
        ),
    ),
    (
        QuestionType.COMPARISON,
        (
            r"\bcompared? (to|with|against)\b",
            r"\bversus\b",
            r"\bvs\.?\b",
            r"\bdifference between\b",
            r"\bmore than\b",
            r"\bfewer than\b",
            r"\bgrew\b",
            r"\bgrowth\b",
            r"\bdecline[ds]?\b",
            r"\bchange[ds]? (in|from)\b",
        ),
    ),
    (
        QuestionType.TREND,
        (
            r"\bover time\b",
            r"\btrend(s|ing)?\b",
            r"\bby (month|week|day|quarter|year)\b",
            r"\bmonth[- ]over[- ]month\b",
            r"\byear[- ]over[- ]year\b",
            r"\beach (month|week|day|quarter|year)\b",
            r"\bmonthly\b",
            r"\bdaily\b",
            r"\bweekly\b",
        ),
    ),
    (
        QuestionType.AGGREGATION,
        (
            r"\bhow many\b",
            r"\bhow much\b",
            r"\btotal\b",
            r"\bsum\b",
            r"\bcount\b",
            r"\baverage\b",
            r"\bavg\b",
            r"\bmean\b",
            r"\bmedian\b",
        ),
    ),
    (
        QuestionType.FILTER,
        (
            r"\bwhich\b",
            r"\bwho\b",
            r"\bwhat\b",
            r"\blist\b",
            r"\bshow\b",
            r"\bfind\b",
            r"\bwhere\b",
        ),
    ),
]

# Relative time windows the SQL generator should be told about explicitly —
# left implicit, models pick inconsistent boundaries for "last quarter".
TIME_WINDOWS: dict[str, str] = {
    r"\blast quarter\b": "the previous complete calendar quarter",
    r"\bthis quarter\b": "the current calendar quarter to date",
    r"\blast month\b": "the previous complete calendar month",
    r"\bthis month\b": "the current calendar month to date",
    r"\blast year\b": "the previous complete calendar year",
    r"\bthis year\b": "the current calendar year to date",
    r"\blast week\b": "the previous complete week",
    r"\byesterday\b": "the previous calendar day",
    r"\btoday\b": "the current calendar day",
    r"\blast (\d+) days?\b": "a rolling window of the given number of days",
    r"\blast (\d+) months?\b": "a rolling window of the given number of months",
    r"\bytd\b": "year to date",
    r"\ball time\b": "no date restriction",
}

# A follow-up that cannot stand alone: it refers back to a previous result.
COREFERENCE_MARKERS = (
    r"\bthat\b",
    r"\bthose\b",
    r"\bthis\b",
    r"\bthese\b",
    r"\bit\b",
    r"\bthem\b",
    r"\bthe same\b",
    r"^\s*(and|also|now|then)\b",
    r"^\s*(break|split|group|filter|sort|order)\b",
)

# Too vague to answer without guessing at the metric.
VAGUE_PATTERNS = (
    r"^\s*(show|tell) me (something|anything|stuff)\b",
    r"^\s*(what'?s|what is) (up|new|going on)\b",
    r"^\s*(data|info|information|report|summary)\s*\??\s*$",
    r"^\s*how (is|are) (it|things|we) (doing|going)\b",
)

MIN_MEANINGFUL_WORDS = 3


@dataclass
class Intent:
    question_type: QuestionType
    """What shape of answer the question calls for."""

    resolved_question: str
    """The question with follow-up context folded in; equals the original
    question when it already stands alone."""

    is_follow_up: bool = False
    needs_clarification: bool = False
    clarification: str | None = None

    time_windows: list[str] = field(default_factory=list)
    """Plain-English readings of any relative dates found, passed to the
    prompt so the model does not invent its own boundaries."""

    limit_hint: int | None = None
    """An explicit row count in the question ("top 5"), if present."""

    @property
    def wants_ordering(self) -> bool:
        return self.question_type in (QuestionType.RANKING, QuestionType.TREND)


def _matches_any(question: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(p, question) for p in patterns)


def _extract_limit(question: str) -> int | None:
    match = re.search(r"\btop\s+(\d+)\b|\bbottom\s+(\d+)\b|\bfirst\s+(\d+)\b", question)
    if not match:
        return None
    value = next(g for g in match.groups() if g)
    return int(value)


def _extract_time_windows(question: str) -> list[str]:
    found = []
    for pattern, description in TIME_WINDOWS.items():
        match = re.search(pattern, question)
        if match:
            found.append(f"'{match.group(0)}' means {description}")
    return found


def _classify(question: str) -> QuestionType | None:
    """The matched question type, or None when nothing matched."""
    for question_type, patterns in PATTERNS:
        if _matches_any(question, patterns):
            return question_type
    return None


def _is_vague(question: str, matched: QuestionType | None) -> bool:
    """Is this question too underspecified to answer without guessing?

    A question that matched an intent pattern is never vague on length
    alone — "top 5 products" is only three words but says exactly what it
    wants. The length check applies only when nothing matched, which is
    where genuinely contentless input ("data?", "info") lands.
    """
    if _matches_any(question, VAGUE_PATTERNS):
        return True
    if matched is not None:
        return False

    words = [w for w in re.findall(r"[a-z0-9]+", question) if len(w) > 1]
    return len(words) < MIN_MEANINGFUL_WORDS


def analyze(question: str, history: list[str] | None = None) -> Intent:
    """Classify a question and resolve it against prior turns.

    ``history`` is previous questions in the session, oldest first.
    """
    original = question.strip()
    normalized = original.lower()

    is_follow_up = bool(history) and _matches_any(normalized, COREFERENCE_MARKERS)

    # A follow-up is judged on the merged text: "break that down by region"
    # is vague alone but perfectly clear after the question it refers to.
    if is_follow_up and history:
        resolved = f"{history[-1].strip()} — follow-up: {original}"
        classify_against = f"{history[-1].lower()} {normalized}"
    else:
        resolved = original
        classify_against = normalized

    matched = _classify(classify_against)

    if not is_follow_up and _is_vague(normalized, matched):
        return Intent(
            question_type=QuestionType.AMBIGUOUS,
            resolved_question=resolved,
            needs_clarification=True,
            clarification=(
                "Could you be more specific about what you'd like to see? "
                "For example, name the metric you care about and the time "
                "period — 'total revenue by month this year'."
            ),
        )

    return Intent(
        # Nothing matched but the question still has substance — treat it as a
        # plain lookup rather than refusing to answer.
        question_type=matched or QuestionType.FILTER,
        resolved_question=resolved,
        is_follow_up=is_follow_up,
        time_windows=_extract_time_windows(normalized),
        limit_hint=_extract_limit(normalized),
    )
