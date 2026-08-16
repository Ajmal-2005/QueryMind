"""Evaluation harness entrypoint.

Phase 0 stood up the scaffolding with a stub predictor. Phase 6 wires the real
pipeline in behind ``--predictor pipeline``, adds the error taxonomy, and adds
the ablation study.

    # schema-linking ablation — needs no API key, produces real numbers
    python -m evaluation.runner --ablation --save

    # the full pipeline, end to end
    python -m evaluation.runner --dataset custom --predictor pipeline --save

Read the provider line in the output before believing any accuracy figure.
Without an ANTHROPIC_API_KEY the pipeline answers with a stub that never reads
the question, and the resulting score is a stub baseline, not a measurement.
"""

import argparse
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from evaluation import ablations, datasets, taxonomy
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
    dataset: str,
    records: Sequence[EvalRecord],
    summary: EvalSummary,
    provenance: dict | None = None,
) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RESULTS_DIR / f"{dataset}-{stamp}.json"

    path.write_text(
        json.dumps(
            {
                "dataset": dataset,
                "run_at": stamp,
                # Which provider and embedder produced these numbers travels
                # with them. A results file that does not say whether a real
                # model answered is a results file that will be misread.
                "provenance": provenance or {},
                "summary": asdict(summary),
                "error_taxonomy": taxonomy.tally(records),
                "records": [asdict(r) for r in records],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def save_ablation(results: list, provenance: dict) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RESULTS_DIR / f"ablation-{stamp}.json"

    path.write_text(
        json.dumps(
            {
                "run_at": stamp,
                "provenance": provenance,
                "arms": ablations.to_dict(results),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _run_ablation(args) -> None:
    """Schema-linking ablation. Needs no API key."""
    from evaluation.harness import bench

    examples = LOADERS[args.dataset](limit=args.limit)

    with bench() as active:
        provenance = {
            "dataset": args.dataset,
            "embedder": active.embedder,
            "tables_indexed": active.tables_indexed,
            "questions": len(examples),
            "note": (
                "Schema-linking only. No language model is involved, so these "
                "numbers do not depend on an API key."
            ),
        }
        print(f"  embedder              {active.embedder}")
        print(f"  tables indexed        {active.tables_indexed}")
        print(f"  questions             {len(examples)}\n")

        results = ablations.run(active, examples)

    print("Schema-linking ablation")
    print(ablations.as_table(results))

    never_found = sorted({t for r in results for t in r.misses})
    if never_found:
        print(f"\n  gold tables missed by at least one arm: {', '.join(never_found)}")

    # The guard that stops this table being over-read. It matters more than
    # the table when the schema is small, which it currently is.
    ok, why = ablations.discriminates(results, provenance["tables_indexed"])
    provenance["discriminative"] = ok
    provenance["discriminative_note"] = why
    if not ok:
        print(f"\n  NOT DISCRIMINATIVE: {why}")

    if args.save:
        print(f"\nSaved to {save_ablation(results, provenance)}")


def _run_benchmark(args) -> None:
    predictor = None
    provenance: dict = {"predictor": args.predictor}

    if args.predictor == "stub":
        records, summary = run(args.dataset, limit=args.limit)
        print(f"Results - {args.dataset}")
        print(summary.as_table())
        if args.save:
            print(
                f"\nSaved to {save_results(args.dataset, records, summary, provenance)}"
            )
        return

    from evaluation import predictors
    from evaluation.harness import bench

    with bench() as active:
        info = predictors.describe(active)
        print("Predictor:")
        for line in info.as_lines():
            print(line)
        print()

        if not info.live_model and args.predictor == "pipeline":
            print(
                "  WARNING: no ANTHROPIC_API_KEY is set. The stub provider will\n"
                "  answer every question without reading it. Whatever accuracy\n"
                "  this prints is a stub baseline and must not be reported as a\n"
                "  measurement of the system.\n"
            )

        predictor = (
            predictors.retrieval_only_predictor(active)
            if args.predictor == "retrieval"
            else predictors.pipeline_predictor(active)
        )
        provenance |= asdict(info) | {"embedder": active.embedder}
        records, summary = run(args.dataset, limit=args.limit, predictor=predictor)

    print(f"Results - {args.dataset}")
    print(summary.as_table())

    if args.predictor == "retrieval":
        print(
            "\n  Retrieval-only run: 'execution accuracy' here means every gold\n"
            "  table was retrieved, not that the right rows came back."
        )

    counts = taxonomy.tally(records)
    if counts:
        print("\nError taxonomy")
        print(taxonomy.as_table(counts))

    if args.save:
        print(f"\nSaved to {save_results(args.dataset, records, summary, provenance)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a text-to-SQL benchmark.")
    parser.add_argument(
        "--dataset", choices=sorted(LOADERS), default="custom", help="benchmark to run"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="cap the question count"
    )
    parser.add_argument(
        "--predictor",
        choices=("stub", "pipeline", "retrieval"),
        default="stub",
        help="stub (phase 0 placeholder), pipeline (the real system), or "
        "retrieval (schema linking only, no API key needed)",
    )
    parser.add_argument(
        "--ablation",
        action="store_true",
        help="run the schema-linking ablation study instead of a benchmark",
    )
    parser.add_argument("--save", action="store_true", help="write results to JSON")
    args = parser.parse_args()

    print("Benchmark data:")
    for name, ok in datasets.available().items():
        print(f"  {'[ok]     ' if ok else '[missing]'} {name}")
    print()

    try:
        if args.ablation:
            _run_ablation(args)
        else:
            _run_benchmark(args)
    except datasets.DatasetNotAvailable as exc:
        # The message already says what is missing; a traceback adds nothing.
        raise SystemExit(f"\n{exc}") from None


if __name__ == "__main__":
    main()
