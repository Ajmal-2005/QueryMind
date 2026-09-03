"""Check everything the demo depends on, then warm the cache.

    python -m scripts.preflight

Written because the same three failures kept recurring: the server started
under the system Python instead of the virtualenv, a provider key that looked
fine but could not serve, and a connection whose schema was never indexed.
Each one is silent until a question is asked in front of an audience.

The warm-up matters as much as the checks. Asking each demo question once puts
its answer in the semantic cache, so the same question asked again is served
without touching the model - immune to rate limits, quota and network for as
long as the cache TTL holds.

Exit code 0 means the app is ready.
"""

import sys
import time
from pathlib import Path

QUESTIONS = [
    "How many customers do we have?",
    "Which customers have never placed an order?",
    "Which product categories generated the most revenue?",
    "Show monthly revenue trend for completed orders",
    "Which suppliers have the longest average lead time?",
    "What is the average order value by region?",
    "Which 5 customers have spent the most in total?",
    "How many orders are in each status?",
    "Top 5 products by price",
    "How many active customers are there per region?",
]

OK, BAD, WARN = "[ ok ]", "[FAIL]", "[warn]"


def main() -> int:
    failures: list[str] = []

    # --- interpreter ---------------------------------------------------
    in_venv = ".venv" in sys.executable.replace("\\", "/")
    print(f"{OK if in_venv else BAD} interpreter   {sys.executable}")
    if not in_venv:
        failures.append(
            "Running under the wrong Python. Start the server with\n"
            "        cd backend; .venv\Scripts\python -m uvicorn "
            "app.main:app --port 8000"
        )

    # --- provider SDKs and keys ----------------------------------------
    from app.core.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()

    from app.services.generation.llm import get_client, sdk_available

    keys = {
        "gemini": settings.GEMINI_API_KEY,
        "openai": settings.OPENAI_API_KEY,
        "anthropic": settings.ANTHROPIC_API_KEY,
    }
    for provider, key in keys.items():
        if not key:
            continue
        have = sdk_available(provider)
        print(
            f"{OK if have else WARN} sdk           {provider}: "
            f"{'importable' if have else 'MISSING - provider will be skipped'}"
        )

    client = get_client()
    chain = [c.name for c in getattr(client, "clients", [client])]
    live = [c for c in chain if c != "stub"]
    print(f"{OK if live else BAD} chain         {' -> '.join(chain)}")
    if not live:
        failures.append(
            "No usable LLM provider. Check keys in .env and the SDKs above."
        )

    # --- database and connection ---------------------------------------
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.connection import Connection, ConnectionStatus

    db = SessionLocal()
    try:
        indexed = db.scalars(
            select(Connection).where(Connection.status == ConnectionStatus.INDEXED)
        ).all()
        # "Indexed" only records what happened at index time. A connection can
        # still be unusable now: the file moved, or - the one that actually
        # happened here - CREDENTIAL_ENCRYPTION_KEY changed and the stored
        # credentials no longer decrypt. Both surface as a 500 mid-demo, so
        # each one is opened for real rather than trusted.
        from app.services.execution.runner import execute

        usable = []
        for c in indexed:
            if c.dialect.value == "sqlite" and not Path(c.database).exists():
                print(f"{WARN} connection    {c.name}: file is missing")
                continue
            try:
                probe = execute(c, "SELECT 1", max_rows=1)
            except Exception as exc:  # noqa: BLE001 - any failure disqualifies it
                print(f"{WARN} connection    {c.name}: {type(exc).__name__}")
                continue
            if not probe.ok:
                print(f"{WARN} connection    {c.name}: {(probe.error or '')[:46]}")
                continue
            usable.append(c)
            print(f"{OK} connection    {c.name} ({c.dialect.value}, opens cleanly)")

        if not usable:
            print(f"{BAD} connection    none usable")
            failures.append(
                "No usable connection. Run:  python -m scripts.reset_demo_state"
            )
            _report(failures)
            return 1

        broken = len(indexed) - len(usable)
        if broken:
            print(
                f"{WARN} {broken} connection(s) indexed but unusable - "
                "delete them so the Ask dropdown stays clean"
            )

        # Pick deliberately. The demo questions are written against the
        # e-commerce schema, and warming them against whichever connection
        # happens to sort first produces ten confident answers about the wrong
        # database. A name can be passed as an argument to override.
        wanted = " ".join(sys.argv[1:]).strip().lower()
        if wanted:
            target = next((c for c in usable if wanted in c.name.lower()), None)
            if target is None:
                print(f"{BAD} no usable connection matching {wanted!r}")
                failures.append(f"No connection named like {wanted!r}")
                _report(failures)
                return 1
        else:
            target = next((c for c in usable if "demo" in c.name.lower()), usable[0])
        print(
            f"\nWarming the cache against '{target.name}' "
            f"(TTL {settings.CACHE_TTL_SECONDS}s)\n"
        )

        # --- warm-up ----------------------------------------------------
        from app.services.generation import pipeline

        real, cached, failed = 0, 0, 0
        for question in QUESTIONS:
            started = time.perf_counter()
            outcome = pipeline.run(
                db=db,
                connection=target,
                question=question,
                user_id=target.user_id,
                session_id="preflight",
            )
            elapsed = time.perf_counter() - started
            model = outcome.generation.model if outcome.generation else "-"

            if not outcome.succeeded:
                failed += 1
                mark, note = WARN, f"did not run: {(outcome.error or '')[:50]}"
            elif outcome.semantic_hit:
                cached += 1
                mark, note = OK, "already cached"
            elif model == "stub":
                failed += 1
                mark, note = WARN, "STUB - no model answered"
            else:
                real += 1
                mark, note = OK, model
            print(f"  {mark} {elapsed:5.1f}s  {note:<34} {question[:44]}")

        print(
            f"\n  {real} answered by a model, {cached} already cached, "
            f"{failed} degraded"
        )
        if failed:
            failures.append(
                f"{failed} question(s) did not get a real answer. They will still "
                "render, but with placeholder SQL."
            )
    finally:
        db.close()

    _report(failures)
    return 1 if failures else 0


def _report(failures: list[str]) -> None:
    print()
    if failures:
        print("NOT READY:")
        for f in failures:
            print(f"  - {f}")
    else:
        print(
            "READY. Ask any warmed question and it is served from cache, "
            "without calling the model."
        )


if __name__ == "__main__":
    sys.exit(main())
