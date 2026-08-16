"""The ablation study.

Research question 1 asks whether hybrid retrieval with foreign-key expansion
links schema better than the alternatives. That question can be answered
*without a language model*: give the system a question, ask which tables it
retrieves, and compare against the tables the gold query actually reads.

That matters here more than it would elsewhere. Every accuracy number in this
project is blocked on an API key; schema-linking recall is not, so this is the
one place the evaluation produces real measurements rather than scaffolding.

Each arm turns off exactly one thing:

- **dense-only** / **sparse-only** — does fusing the two retrievers beat
  either alone?
- **no-expansion** (`hops=0`) — does walking the foreign-key graph recover
  the join tables ranking misses? This is the arm that speaks most directly
  to the proposal's motivating example, where a junction table no retriever
  ranks highly is nonetheless required for the join.
- **top-k sweep** — how much of recall is just retrieving more?

The last one is the honest control. A recall win that a larger `k` also buys
is not a win for the method, and reporting it as one would be the easiest
mistake in this whole study to make.
"""

from dataclasses import asdict, dataclass, field

from evaluation import datasets
from evaluation.harness import Bench
from evaluation.metrics import EvalRecord, schema_linking_recall
from evaluation.predictors import retrieval_only_predictor


@dataclass
class Arm:
    """One configuration under test."""

    name: str
    description: str
    mode: str = "hybrid"
    hops: int | None = None
    top_k: int | None = None


@dataclass
class ArmResult:
    name: str
    description: str
    questions: int
    recall: float
    """Mean fraction of gold tables retrieved."""

    perfect: int
    """Questions where every gold table was found — the metric that matters,
    because a query needs *all* its tables, not most of them."""

    perfect_rate: float
    mean_tables_retrieved: float
    """The cost side. Recall bought by retrieving everything is not a result."""

    mean_latency_ms: float
    coverage: float = 0.0
    """Mean fraction of the whole schema retrieved. The number that decides
    whether this arm's recall means anything — see `discriminates()`."""

    misses: list[str] = field(default_factory=list)
    """Gold tables never retrieved, for the error analysis."""


# The shipping configuration first, so every other row reads as a delta.
DEFAULT_ARMS: tuple[Arm, ...] = (
    Arm("hybrid+fk", "RRF over dense and BM25, one hop of FK expansion"),
    Arm("hybrid, no expansion", "RRF, foreign-key expansion disabled", hops=0),
    Arm("dense only", "Embeddings only, with FK expansion", mode="dense"),
    Arm("dense, no expansion", "Embeddings only, no expansion", mode="dense", hops=0),
    Arm("sparse only", "BM25 only, with FK expansion", mode="sparse"),
    Arm("sparse, no expansion", "BM25 only, no expansion", mode="sparse", hops=0),
    Arm("hybrid+fk, k=1", "Does a smaller candidate set still work?", top_k=1),
    Arm("hybrid+fk, k=3", "Between the default and one", top_k=3),
    Arm("hybrid+fk, k=10", "The control: recall bought by retrieving more", top_k=10),
)


def _score(records: list[EvalRecord]) -> tuple[float, int, list[str]]:
    usable = [r for r in records if r.gold_tables]
    if not usable:
        return 0.0, 0, []

    # Mean of per-question recall, not recall over the pooled table sets: a
    # question needing four tables should not outweigh one needing two.
    recall = sum(
        schema_linking_recall(r.retrieved_tables, r.gold_tables) for r in usable
    ) / len(usable)

    perfect = 0
    misses: list[str] = []
    for record in usable:
        retrieved = {t.lower() for t in record.retrieved_tables}
        missing = [t for t in record.gold_tables if t.lower() not in retrieved]
        if missing:
            misses.extend(missing)
        else:
            perfect += 1

    return recall, perfect, misses


# Above this share of the schema retrieved, an arm is close to sending
# everything and its recall says little about the ranking. Chosen as "half":
# retrieve more than half the schema and the retriever is barely choosing.
COVERAGE_CEILING = 0.5


def discriminates(results: list[ArmResult], schema_size: int) -> tuple[bool, str]:
    """Can this schema tell the arms apart at all?

    The honest guard on the whole study. On a small schema the default `top_k`
    retrieves most of the tables, every arm scores near 100%, and the numbers
    look like a resounding success while measuring almost nothing. Saying so
    is worth more than the table above it.
    """
    if not results:
        return False, "no arms were run"

    baseline = results[0]
    if baseline.coverage >= COVERAGE_CEILING:
        return False, (
            f"the default configuration retrieves {baseline.coverage:.0%} of a "
            f"{schema_size}-table schema, so nearly every arm finds nearly "
            "every gold table. These numbers do not separate the methods; they "
            "mostly show the schema is small. Run against Spider or BIRD."
        )

    spread = max(r.recall for r in results) - min(r.recall for r in results)
    if spread < 0.05:
        return False, (
            f"every arm lands within {spread:.1%} of the others — too close to "
            "attribute to the method rather than to noise."
        )

    return True, ""


def run_arm(
    bench: Bench, arm: Arm, examples: list[datasets.BenchmarkExample]
) -> ArmResult:
    predict = retrieval_only_predictor(
        bench, top_k=arm.top_k, hops=arm.hops, mode=arm.mode
    )
    records = [predict(example) for example in examples]
    recall, perfect, misses = _score(records)

    usable = [r for r in records if r.gold_tables] or records
    schema_size = max(bench.tables_indexed, 1)
    return ArmResult(
        name=arm.name,
        description=arm.description,
        questions=len(usable),
        recall=recall,
        perfect=perfect,
        perfect_rate=perfect / len(usable) if usable else 0.0,
        mean_tables_retrieved=(
            sum(len(r.retrieved_tables) for r in usable) / len(usable)
            if usable
            else 0.0
        ),
        mean_latency_ms=(
            sum(r.latency_ms for r in usable) / len(usable) if usable else 0.0
        ),
        coverage=(
            sum(len(r.retrieved_tables) for r in usable) / (len(usable) * schema_size)
            if usable
            else 0.0
        ),
        misses=sorted(set(misses)),
    )


def run(
    bench: Bench,
    examples: list[datasets.BenchmarkExample],
    arms: tuple[Arm, ...] = DEFAULT_ARMS,
) -> list[ArmResult]:
    return [run_arm(bench, arm, examples) for arm in arms]


def as_table(results: list[ArmResult]) -> str:
    """ASCII only — Windows consoles mangle box drawing."""
    if not results:
        return "  (no arms run)"

    width = max(len(r.name) for r in results)
    header = (
        f"  {'arm':<{width}}  {'recall':>7}  {'all-found':>10}  "
        f"{'tables':>7}  {'schema':>7}  {'ms':>6}"
    )
    lines = [header, "  " + "-" * (len(header) - 2)]

    baseline = results[0]
    for result in results:
        delta = ""
        if result is not baseline:
            change = result.recall - baseline.recall
            delta = f"  ({change:+.1%})" if abs(change) > 1e-9 else "  (=)"
        lines.append(
            f"  {result.name:<{width}}  {result.recall:>7.1%}  "
            f"{result.perfect_rate:>10.1%}  "
            f"{result.mean_tables_retrieved:>7.1f}  "
            f"{result.coverage:>7.0%}  "
            f"{result.mean_latency_ms:>6.1f}{delta}"
        )

    lines += [
        "",
        "  recall     = mean fraction of the gold query's tables retrieved",
        "  all-found  = questions where EVERY gold table was retrieved",
        "  tables     = mean tables sent to the prompt (the cost side)",
        "  schema     = share of the WHOLE schema retrieved; near 100% means",
        "               the retriever is barely choosing and recall is cheap",
    ]
    return "\n".join(lines)


def to_dict(results: list[ArmResult]) -> list[dict]:
    return [asdict(r) for r in results]


__all__ = ["DEFAULT_ARMS", "Arm", "ArmResult", "as_table", "run", "run_arm", "to_dict"]
