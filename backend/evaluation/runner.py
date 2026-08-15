"""Evaluation harness entrypoint.

Phase 0 stands up the scaffolding: dataset loading, the record/summary types,
and reporting. The pipeline it calls does not exist until phase 2, so the
default predictor is a stub and the harness reports 0% — which is the correct
baseline, not a failure.

    python -m evaluation.runner --dataset custom --limit 10
"""

import argparse
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from evaluation import datasets
from evaluation.metrics import EvalRecord, EvalSummary, summarize

RESULTS_DIR = Path(__file__).parent / "results"


class Predictor(Protocol):
    """What the harness needs from the NL→SQL pipeline."""

    def __call__(self, example: datasets.BenchmarkExample) -> EvalRecord: ...


def stub_predictor(example: datasets.BenchmarkExample) -> EvalRecord:
    """Placeholder until the phase 2 pipeline lands."""
    return EvalRecord(
        question_id=example.question_id,
        question=example.question,
        db_id=example.db_id,
        gold_sql=example.gold_sql,
        predicted_sql=None,
        correct=False,
        executed=False,
        error="pipeline not implemented (phase 2)",
        error_category="not_implemented",
    )


LOADERS: dict = {
    "spider": datasets.load_spider_dev,
    "bird": datasets.load_bird_dev,
    "custom": datasets.load_custom_set,
}


def run(
    dataset: str,
    limit: int | None = None,
    predictor: Predictor | None = None,
) -> tuple[list[EvalRecord], EvalSummary]:
    loader: Callable = LOADERS[dataset]
    examples = loader(limit=limit)
    predict = predictor or stub_predictor

    records: list[EvalRecord] = []
    for example in examples:
        started = time.perf_counter()
        record = predict(example)
        # Only time the run here if the predictor did not report its own.
        if not record.latency_ms:
            record.latency_ms = (time.perf_counter() - started) * 1000
        records.append(record)

    return records, summarize(records)


def save_results(
    dataset: str, records: Sequence[EvalRecord], summary: EvalSummary
) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RESULTS_DIR / f"{dataset}-{stamp}.json"

    path.write_text(
        json.dumps(
            {
                "dataset": dataset,
                "run_at": stamp,
                "summary": asdict(summary),
                "records": [asdict(r) for r in records],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a text-to-SQL benchmark.")
    parser.add_argument(
        "--dataset", choices=sorted(LOADERS), default="custom", help="benchmark to run"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="cap the question count"
    )
    parser.add_argument("--save", action="store_true", help="write results to JSON")
    args = parser.parse_args()

    present = datasets.available()
    print("Benchmark data:")
    for name, ok in present.items():
        print(f"  {'[ok]     ' if ok else '[missing]'} {name}")
    print()

    try:
        records, summary = run(args.dataset, limit=args.limit)
    except datasets.DatasetNotAvailable as exc:
        # The message already says what is missing; a traceback adds nothing.
        raise SystemExit(f"\n{exc}") from None

    # ASCII only: Windows consoles default to cp1252 and mangle box drawing.
    print(f"Results - {args.dataset}")
    print(summary.as_table())

    if args.save:
        print(f"\nSaved to {save_results(args.dataset, records, summary)}")


if __name__ == "__main__":
    main()
