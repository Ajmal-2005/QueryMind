"""Concurrency check against a running server.

    python -m scripts.load_test --users 20 --requests 200

Not a benchmark of the language model - with no API key the stub answers
instantly, and the numbers below measure the *plumbing*: connection pooling,
the result cache, the gates, JSON serialisation, and whether anything
deadlocks when twenty people ask at once.

That is worth measuring on its own. Every SQLite path in this system is
single-writer, the cache is a process-local dict behind a lock, and the
sandboxed executor opens an engine per query. Any of those could serialise
under load, and none of it had ever been run concurrently before this.

Latency here is therefore a floor, not a forecast. A real model adds
seconds that dwarf everything measured below.
"""

import argparse
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import httpx

# 127.0.0.1, never "localhost". On a machine where localhost resolves to ::1
# first and the server listens only on IPv4, every request pays a ~2 s
# connection timeout before falling back - which this script originally
# measured and misattributed to the application.
DEFAULT_BASE = "http://127.0.0.1:8000/api/v1"

QUESTIONS = (
    "How many customers do we have?",
    "Top 5 products by price",
    "What is total revenue by month?",
    "Which customers have never placed an order?",
    "Revenue by region",
)


@dataclass
class Outcome:
    latencies: list[float] = field(default_factory=list)
    statuses: dict[int, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def record(self, status: int, elapsed: float) -> None:
        self.latencies.append(elapsed)
        self.statuses[status] = self.statuses.get(status, 0) + 1


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, min(len(ordered), round(pct / 100 * len(ordered))))
    return ordered[rank - 1]


def login(base: str, email: str, password: str) -> str:
    response = httpx.post(
        f"{base}/auth/login", json={"email": email, "password": password}, timeout=30
    )
    response.raise_for_status()
    return response.json()["access_token"]


def first_indexed_connection(base: str, token: str) -> str:
    response = httpx.get(
        f"{base}/connections",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    response.raise_for_status()
    indexed = [c for c in response.json() if c["status"] == "indexed"]
    if not indexed:
        raise SystemExit("No indexed connection. Index one before load testing.")
    return indexed[0]["id"]


def run(base: str, token: str, connection_id: str, users: int, total: int) -> Outcome:
    outcome = Outcome()
    headers = {"Authorization": f"Bearer {token}"}

    def one(index: int) -> None:
        question = QUESTIONS[index % len(QUESTIONS)]
        started = time.perf_counter()
        try:
            response = httpx.post(
                f"{base}/query",
                headers=headers,
                json={"connection_id": connection_id, "question": question},
                timeout=120,
            )
            outcome.record(response.status_code, (time.perf_counter() - started) * 1000)
        except Exception as exc:  # noqa: BLE001 - a failure is a datapoint
            outcome.errors.append(str(exc)[:120])

    # Threads, not asyncio: the endpoints are sync and FastAPI runs them in a
    # thread pool, so this exercises the same concurrency the server sees.
    with ThreadPoolExecutor(max_workers=users) as pool:
        list(pool.map(one, range(total)))

    return outcome


def main() -> None:
    parser = argparse.ArgumentParser(description="Concurrency check.")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--users", type=int, default=10, help="concurrent workers")
    parser.add_argument("--requests", type=int, default=100, help="total requests")
    args = parser.parse_args()

    token = login(args.base, args.email, args.password)
    connection_id = first_indexed_connection(args.base, token)

    print(f"  {args.requests} requests, {args.users} concurrent\n")
    started = time.perf_counter()
    outcome = run(args.base, token, connection_id, args.users, args.requests)
    wall = time.perf_counter() - started

    ok = outcome.statuses.get(200, 0)
    print("Load test")
    print(f"  wall clock            {wall:.1f} s")
    print(f"  throughput            {args.requests / wall:.1f} req/s")
    print(f"  succeeded             {ok}/{args.requests}")
    print(f"  status codes          {dict(sorted(outcome.statuses.items()))}")
    if outcome.latencies:
        print(f"  latency mean          {statistics.fmean(outcome.latencies):.0f} ms")
        print(f"  latency p50           {_percentile(outcome.latencies, 50):.0f} ms")
        print(f"  latency p95           {_percentile(outcome.latencies, 95):.0f} ms")
        print(f"  latency p99           {_percentile(outcome.latencies, 99):.0f} ms")
    if outcome.errors:
        print(f"  transport errors      {len(outcome.errors)}")
        for error in outcome.errors[:5]:
            print(f"    {error}")

    print(
        "\n  Measures the plumbing, not the model. Without an API key the stub\n"
        "  answers instantly; a real provider adds seconds on top of these."
    )


if __name__ == "__main__":
    main()
