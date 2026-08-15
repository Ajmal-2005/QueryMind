"""Benchmark dataset loading.

Spider and BIRD are large and licence-gated, so they are not vendored. Drop
the extracted archives under ``evaluation/data/`` and these loaders pick them
up; until then they raise a message saying exactly what is missing and where
to put it.
"""

import json
from dataclasses import dataclass
from pathlib import Path

DATA_ROOT = Path(__file__).parent / "data"

DOWNLOAD_HINTS = {
    "spider": "https://yale-lily.github.io/spider",
    "spider-realistic": "https://zenodo.org/records/5205322",
    "bird": "https://bird-bench.github.io/",
}


@dataclass
class BenchmarkExample:
    question_id: str
    question: str
    db_id: str
    gold_sql: str
    difficulty: str | None = None


class DatasetNotAvailable(RuntimeError):
    """Raised when benchmark files have not been downloaded yet."""


def _require(path: Path, dataset: str) -> None:
    if not path.exists():
        hint = DOWNLOAD_HINTS.get(dataset, "")
        raise DatasetNotAvailable(
            f"{dataset} not found at {path}.\n"
            f"Download it from {hint} and extract into {DATA_ROOT}."
        )


def load_spider_dev(limit: int | None = None) -> list[BenchmarkExample]:
    """Spider dev set — 1,034 questions across 20 databases."""
    path = DATA_ROOT / "spider" / "dev.json"
    _require(path, "spider")

    raw = json.loads(path.read_text(encoding="utf-8"))
    examples = [
        BenchmarkExample(
            question_id=f"spider-dev-{i}",
            question=item["question"],
            db_id=item["db_id"],
            gold_sql=item["query"],
        )
        for i, item in enumerate(raw)
    ]
    return examples[:limit] if limit else examples


def load_bird_dev(limit: int | None = None) -> list[BenchmarkExample]:
    """BIRD dev set — 1,534 questions over large, dirty schemas."""
    path = DATA_ROOT / "bird" / "dev.json"
    _require(path, "bird")

    raw = json.loads(path.read_text(encoding="utf-8"))
    examples = [
        BenchmarkExample(
            question_id=f"bird-dev-{i}",
            question=item["question"],
            db_id=item["db_id"],
            # BIRD names the gold column SQL, not query.
            gold_sql=item.get("SQL") or item.get("query", ""),
            difficulty=item.get("difficulty"),
        )
        for i, item in enumerate(raw)
    ]
    return examples[:limit] if limit else examples


def load_custom_set(limit: int | None = None) -> list[BenchmarkExample]:
    """Hand-written questions against the demo e-commerce schema.

    Unlike Spider and BIRD this one lives in the repository, so it is the
    set CI can run against.
    """
    path = Path(__file__).parent / "custom_set.json"
    _require(path, "custom")

    raw = json.loads(path.read_text(encoding="utf-8"))
    examples = [
        BenchmarkExample(
            question_id=item.get("id", f"custom-{i}"),
            question=item["question"],
            db_id=item.get("db_id", "ecommerce"),
            gold_sql=item["gold_sql"],
            difficulty=item.get("difficulty"),
        )
        for i, item in enumerate(raw)
    ]
    return examples[:limit] if limit else examples


def available() -> dict:
    """Report which benchmarks are present, for the harness banner."""
    return {
        "spider": (DATA_ROOT / "spider" / "dev.json").exists(),
        "bird": (DATA_ROOT / "bird" / "dev.json").exists(),
        "custom": (Path(__file__).parent / "custom_set.json").exists(),
    }
