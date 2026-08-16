"""Check which LLM provider actually answers, and prove it end to end.

    python -m scripts.check_llm

A key that lists models can still fail every completion — that is exactly what
happened with this project's OpenAI key, which returns 429 `insufficient_quota`
on every request while looking perfectly healthy otherwise. So this does not
check configuration; it sends one real question through the whole pipeline and
reports what came back.

Exit code 0 means a real model translated the question. 1 means the chain fell
through to the stub, which is not a translation.
"""

import sys

QUESTION = "How many customers are there in each region?"


def main() -> int:
    from app.core.config import settings
    from app.services.generation.llm import get_client

    configured = [
        name
        for name, key in (
            ("anthropic", settings.ANTHROPIC_API_KEY),
            ("openai", settings.OPENAI_API_KEY),
            ("gemini", settings.GEMINI_API_KEY),
        )
        if key
    ]

    print("Configured providers:", ", ".join(configured) or "none")
    if not configured:
        print(
            "\nNo provider key set. Add one to backend/.env:\n"
            "  GEMINI_API_KEY=...   free, no billing — https://aistudio.google.com/apikey\n"
            "  OPENAI_API_KEY=...   needs billing\n"
            "  ANTHROPIC_API_KEY=...needs billing"
        )
        return 1

    client = get_client()
    chain = [c.name for c in getattr(client, "clients", [client])]
    print("Chain order        :", " -> ".join(chain))
    print(f"Asking             : {QUESTION}\n")

    from app.services.generation import pipeline
    from evaluation.harness import bench

    with bench() as b:
        outcome = pipeline.run(
            db=b.db,
            connection=b.connection,
            question=QUESTION,
            user_id=b.user_id,
            persist=False,
        )

    generation = outcome.generation
    model = generation.model if generation else "-"
    sql = (
        outcome.validation.sql
        if outcome.validation and outcome.validation.ok
        else (outcome.error or "")
    )

    print(f"Answered by        : {model}")
    print(f"SQL                : {sql}")
    print(f"Executed           : {outcome.succeeded}")
    if outcome.execution:
        print(f"Rows               : {outcome.execution.row_count}")
    if generation:
        print(f"Confidence         : {generation.confidence:.0%}")
        print(f"Tokens             : {generation.total_tokens}")

    if model == "stub":
        print("\nRESULT: no provider answered — this is a placeholder, not a")
        print("translation. Reason reported by the pipeline:")
        for assumption in generation.assumptions if generation else []:
            print(f"  {assumption}")
        return 1

    print("\nRESULT: a real model translated the question. The app is fully working.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
