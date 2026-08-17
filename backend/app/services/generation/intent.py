"""Intent analysis.

Classifies a question before retrieval so the rest of the pipeline knows what
shape of answer to expect, and resolves follow-ups ("break that down by
region") against the conversation so far.

Rule-based rather than an LLM call. The proposal budgets 300 ms for this
stage; a round-trip cannot meet that, and the classification is only used to
steer the prompt and the later chart choice - a wrong label degrades quality
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

# Relative time windows the SQL generator should be told about explicitly -
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

# A follow-up with no pronoun at all. "Just the north region" and "only last
# month" are refinements of whatever came before, and treating them as new
# questions loses the subject entirely.
ELLIPTICAL_MARKERS = (
    r"^\s*(just|only|but|except|exclude|excluding|include|including|without)\b",
    r"^\s*(what|how) about\b",
    r"^\s*(per|by|for)\b",
    r"^\s*(descending|ascending|reversed?)\b",
    r"^\s*(more|fewer|less)\b",
)

# What a follow-up is asking the previous question to do. Named so the
# resolved question reads as an instruction rather than two glued sentences -
# models handle "grouped additionally by region" far better than
# "revenue last quarter - follow-up: break that down by region".
REFINEMENTS: tuple[tuple[str, str], ...] = (
    (
        r"\b(break(ing)? (it |that |them )?down|split|group)\b",
        "grouped additionally by",
    ),
    (r"\b(exclude|excluding|without|except)\b", "excluding"),
    (r"\b(add|also (show|include)|include)\b", "additionally showing"),
    (r"\b(filter|only|just|restrict|limit to|where)\b", "restricted to"),
    # "sort"/"order"/"rank" only where they are *verbs*. `order` is a noun in
    # every schema this product touches, and "also show order counts" asks for
    # a column, not a sort - which is why this rule is last and this narrow.
    (r"\b(sort|order|rank)(ed|ing)?\s+by\b|^\s*(sort|order|rank)\b", "ordered by"),
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

    clarification_options: list[str] = field(default_factory=list)
    """Concrete rewrites the user can pick instead of retyping (F20). Empty
    when the question was answerable."""

    missing: list[str] = field(default_factory=list)
    """What the question did not specify - 'metric', 'time period'. Drives the
    targeted clarification rather than one generic prompt."""

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


def _refinement_verb(question: str) -> tuple[str, str | None]:
    """How this follow-up modifies the previous question, and what said so."""
    for pattern, phrasing in REFINEMENTS:
        if re.search(pattern, question):
            return phrasing, pattern
    return "refined by", None


def _resolve_follow_up(original: str, normalized: str, previous: str) -> str:
    """Fold a follow-up into the question it refers to.

    Phrased as a single instruction rather than two glued sentences. The
    instruction words are then removed from the tail, so "break that down by
    region" becomes "…, grouped additionally by: region" rather than repeating
    itself - the model is being told what to do once, not twice.

    The previous turn is the *resolved* question of that turn, so a chain of
    follow-ups accumulates rather than each one only seeing the turn before:
    "revenue last quarter" → "…by region" → "…just the north" has to keep the
    time window from two turns back.
    """
    verb, pattern = _refinement_verb(normalized)

    trailing = original.strip()
    # The instruction goes first: "also" is both a connective and part of
    # "also show", and stripping the connective first would leave a dangling
    # "show" that the instruction pattern can no longer match.
    if pattern:
        trailing = re.sub(pattern, "", trailing, count=1, flags=re.I)
    # Then the leading connective, which is noise once the sentences are merged.
    trailing = re.sub(r"^\s*(and|also|now|then|but)\b[,\s]*", "", trailing, flags=re.I)
    # And the preposition it left behind: "…down by region" → "region".
    trailing = re.sub(
        r"^[\s,]*(by|to|on|for|into)\b\s*", "", trailing.strip(), flags=re.I
    )

    # If stripping consumed everything, the original phrasing was all
    # instruction and no object; fall back rather than emit a dangling colon.
    return f"{previous.strip()}, {verb}: {trailing.strip() or original.strip()}"


def _clarify(question: str, matched: QuestionType | None) -> Intent | None:
    """Ask for exactly what is missing (F20), or None when nothing is.

    A single generic "please be more specific" is the easy implementation and
    the useless one - the user already knows their question was vague, and
    what they need is to be told *which part*. So the checks are separate and
    each carries its own concrete rewrites.
    """
    if _matches_any(question, VAGUE_PATTERNS):
        return Intent(
            question_type=QuestionType.AMBIGUOUS,
            resolved_question=question,
            needs_clarification=True,
            missing=["metric", "time period"],
            clarification=(
                "That could mean almost anything in this database. Which "
                "measure do you want, and over what period?"
            ),
            clarification_options=[
                "Total revenue by month this year",
                "Number of orders last quarter",
                "Top 10 customers by spend",
            ],
        )

    # Deliberately *not* here: "top customers" with no measure named. It is
    # genuinely ambiguous - revenue, order count and recency give three
    # different answers - but Phase 2 decided such questions get answered with
    # the assumption stated rather than refused, and that decision holds. F20
    # is about making the clarifications that already fire more useful, not
    # about refusing more questions.

    words = [w for w in re.findall(r"[a-z0-9]+", question) if len(w) > 1]
    if matched is None and len(words) < MIN_MEANINGFUL_WORDS:
        return Intent(
            question_type=QuestionType.AMBIGUOUS,
            resolved_question=question,
            needs_clarification=True,
            missing=["metric", "time period"],
            clarification=(
                "There is not quite enough there to build a query from. Name "
                "the measure you want and, if it matters, the period."
            ),
            clarification_options=[
                "Total revenue by month this year",
                "How many customers signed up last month",
            ],
        )

    return None


def analyze(question: str, history: list[str] | None = None) -> Intent:
    """Classify a question and resolve it against prior turns.

    ``history`` is previous questions in the session, oldest first. Pass the
    *resolved* text of each turn where possible, so a chain of follow-ups
    accumulates context rather than each one seeing only the turn before.
    """
    original = question.strip()
    normalized = original.lower()

    is_follow_up = bool(history) and (
        _matches_any(normalized, COREFERENCE_MARKERS)
        or _matches_any(normalized, ELLIPTICAL_MARKERS)
    )

    # A follow-up is judged on the merged text: "break that down by region"
    # is vague alone but perfectly clear after the question it refers to.
    if is_follow_up and history:
        resolved = _resolve_follow_up(original, normalized, history[-1])
        classify_against = f"{history[-1].lower()} {normalized}"
    else:
        resolved = original
        classify_against = normalized

    matched = _classify(classify_against)

    if not is_follow_up and (clarification := _clarify(normalized, matched)):
        clarification.resolved_question = resolved
        return clarification

    return Intent(
        # Nothing matched but the question still has substance - treat it as a
        # plain lookup rather than refusing to answer.
        question_type=matched or QuestionType.FILTER,
        resolved_question=resolved,
        is_follow_up=is_follow_up,
        # Time windows are read from the merged text so a follow-up inherits
        # "last quarter" from the question it refines.
        time_windows=_extract_time_windows(classify_against),
        limit_hint=_extract_limit(classify_against),
    )
