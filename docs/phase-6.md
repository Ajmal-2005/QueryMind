# Phase 6 - Hardening & Evaluation

Weeks 14-15. The phase the proposal calls highest-risk, because it is where
the numbers come from.

**The headline, stated first because everything else depends on it: there is
still no `ANTHROPIC_API_KEY`, so no accuracy figure has been produced. What
this phase built is the machinery that produces them, plus the one measurement
that does not need a model - and that measurement returned a result worth
reporting.**

---

## What was built

| Piece | Where | Purpose |
|---|---|---|
| Gold-query parsing | `evaluation/gold.py` | Extract the tables a benchmark answer reads |
| Real predictor | `evaluation/predictors.py` | Wire `pipeline.run` into the harness |
| Live benchmark fixture | `evaluation/harness.py` | Throwaway indexed database per run |
| Error taxonomy | `evaluation/taxonomy.py` | Classify *how* a wrong answer is wrong |
| Ablation study | `evaluation/ablations.py` | Isolate each retrieval component |
| Retrieval modes | `linking/retriever.py` | `mode=` and `hops=` knobs for the arms |
| Token & cost tracking | `api/v1/usage.py` | `GET /usage` (Appendix B), per-user spend |
| RBAC | `api/v1/usage.py` | First use of `require_roles`, on the audit trail |
| Load test | `scripts/load_test.py` | Concurrency behaviour of the plumbing |

### The predictor slot is filled

Phase 0 left a stub with a note. `--predictor pipeline` now calls the real
`pipeline.run` - same retrieval, same four gates, same sandboxed execution -
so the harness measures the system rather than a reimplementation of it. The
ablation knobs are threaded *through* `pipeline.run` for the same reason.

Every run records which provider and embedder produced it, and the runner
prints a warning when the stub is answering. A results file that does not say
whether a real model was involved is a results file that will be misread.

### Gold-table extraction

Schema-linking recall needs the tables the gold query reads, which benchmarks
do not supply. Parsed with sqlglot rather than a regex, because a regex over
`FROM (\w+)` misses joins, subqueries and CTE bodies, counts CTE names and
aliases as tables, and every one of those errors *inflates* recall by shrinking
the denominator.

### Error taxonomy

Ordered most to least fundamental, first match wins. A query on the wrong table
also has the wrong columns; reporting that as a column error sends you looking
in the wrong place.

Carried into the report as a caveat: this compares surface structure, so two
correct-but-differently-written queries can register as a difference. It is
only ever applied to answers already known to be wrong.

---

## Verified - with real numbers

**547 backend tests pass**, ruff clean, frontend builds and lints clean.

### Schema-linking ablation (no API key required)

`python -m evaluation.runner --ablation --save`, 10 custom questions, 8-table
demo schema, `hashing-local` embedder:

| arm | recall | all-found | tables | schema |
|---|---|---|---|---|
| **hybrid+fk** (shipping) | 100.0% | 100.0% | 7.8 | 98% |
| hybrid, no expansion | 97.5% | 90.0% | 6.0 | 75% |
| dense only | 100.0% | 100.0% | 7.6 | 95% |
| dense, no expansion | 97.5% | 90.0% | 6.0 | 75% |
| sparse only | 100.0% | 100.0% | 8.0 | 100% |
| sparse, no expansion | 94.2% | 80.0% | 6.0 | 75% |
| hybrid+fk, k=1 | 87.5% | 80.0% | 2.8 | 35% |
| hybrid+fk, k=3 | 97.5% | 90.0% | 5.1 | 64% |
| hybrid+fk, k=10 | 100.0% | 100.0% | 8.0 | 100% |

**The harness declares this result non-discriminative, and it is right to.**
The default configuration retrieves 98% of an 8-table schema. Nearly every arm
finds nearly every gold table because nearly every table is being sent. The
`schema` column exists precisely to make that visible, and `discriminates()`
refuses to let the table be read as a success.

What can honestly be said from it:

1. **Foreign-key expansion does help**, consistently: +2.5 points of recall
   and +10 points of all-found across every retrieval mode, and +5.8 / +20 for
   BM25 alone. Directionally this supports research question 1.
2. **Hybrid fusion shows no benefit at this scale.** Dense-only and sparse-only
   both reach 100% with expansion. RRF cannot demonstrate value on a schema
   where retrieving six of eight tables is enough.
3. **The `k=10` control retrieves the entire schema and also scores 100%**,
   which is the whole reason the control exists. Any recall claim that a larger
   `k` also buys is not a claim for the method.
4. **Only `k=1` discriminates** (87.5% / 80%), and one arm is not a study.

The correct conclusion is that this schema cannot answer research question 1.
Spider (200+ databases, many with 20+ tables) can. That is now the single most
valuable thing to add after an API key.

### Load test

`python -m scripts.load_test --users N --requests 40`, stub provider:

| concurrency | throughput | p50 latency |
|---|---|---|
| 1 | 8.0 req/s | 123 ms |
| 5 | 8.6 req/s | 573 ms |
| 20 | 8.5 req/s | 1861 ms |

200/200 requests succeeded at 20-way concurrency - nothing deadlocks, and the
process-local cache lock and per-query engine creation hold up.

But **throughput is flat at ~8.5 req/s while latency grows linearly with
concurrency**, which is the signature of complete serialisation: the system
processes the same total work per second no matter how many clients wait. The
cause is structural and known - SQLite permits one writer, every answered
question writes a `queries` row and an `audit_log` row, and uvicorn is running
a single worker. Postgres is the documented deployment target and would remove
the write serialisation; it has never been run.

This is a floor, not a forecast. A real model adds seconds that dwarf all of
the above.

### Token, cost and RBAC

- `GET /usage` reports queries, tokens, estimated cost and mean latency,
  scoped to the caller - or to everyone, with a per-user breakdown, for an
  admin. Rates travel with every response.
- `GET /usage/audit` is the first endpoint in the project to use
  `require_roles`, which had existed unused since Phase 0. A non-admin gets
  403.

---

## Not verified

1. **No accuracy has been measured, still.** Phase 2's ≥65% and Phase 3's ≥75%
   gates remain unmet *and unmeasurable*. The machinery is now complete and
   waiting on one environment variable.
2. **Spider, Spider-Realistic and BIRD are not downloaded.** The loaders and
   gold-table extraction are ready; the data is not there.
3. **The ablation is non-discriminative** on the only available schema, as the
   harness itself reports.
4. **The embedder comparison was not run.** It needs an `OPENAI_API_KEY` to
   have a second arm; comparing the local embedder against itself is not a
   comparison.
5. **`--predictor pipeline` has only ever run against the stub**, which ignores
   the question. It exercises the plumbing end to end and produces a 0%-shaped
   baseline, which is correct and uninteresting.
6. **Postgres, Redis, Docker, MySQL** - unchanged from every previous phase.
7. **No accessibility audit was run.** Keyboard navigation and contrast were
   considered while building, but nothing was tested with a screen reader or an
   automated checker, and I will not claim otherwise.

---

## Decisions

| Decision | Why |
|---|---|
| **Ablation knobs live in `retrieve()`, not the harness** | A harness that reimplements retrieval measures the reimplementation. |
| **The harness builds a throwaway database** | A benchmark that writes 1,034 rows into the app you are demoing tomorrow is its own kind of bug. `persist=False` for the same reason: benchmark questions must not poison the few-shot pool. |
| **Retrieval-only "accuracy" means all gold tables found** | Execution accuracy is undefined without a model. Reporting it as 0% would be misleading, so the metric is redefined and the runner says so. |
| **`discriminates()` reports when the study proves nothing** | The strongest possible result here would be a table of 100%s that means nothing. Saying so is worth more than the table. |
| **Cost is an estimate, and labelled one** | `queries.tokens_used` is a combined total split by an assumed 85/15 ratio. Indicative of spend, not an invoice. |
| **Rates are returned with every response** | Prices change; a stored cost silently becomes wrong, and a number with no rate beside it cannot be corrected. |
| **Usage is scoped by role, not a flag** | Another user's question volume is a privacy leak, not a reporting feature. |
| **An unknown model costs the default rate, not zero** | Costing an unrecognised model at zero would hide real spend. |

---

## Bugs and mistakes found

**1. I misdiagnosed a 2-second latency and nearly reported it.**

The first load test showed ~2.1 s per request against a pipeline reporting
80 ms of work. I attributed the gap to `similar_examples` embedding the whole
query history, wrote a lexical pre-filter, and left a comment in the source
claiming a load test had measured it at ~2 s.

That was wrong. Every endpoint - including `/health` - took exactly ~2028 ms,
which is not what a data-dependent cost looks like. The cause was the *client*:
`localhost` resolved to `::1` first, the server listens on IPv4 only, and every
request paid a connection timeout before falling back. Against `127.0.0.1` the
same endpoint answers in 4 ms.

Both the load-test default and the false comment are fixed. The pre-filter was
kept - bounding a cost that grows with history is still right - but it is now
described as what it is, an unbounded slope caught early, not a 2-second fix.

The lesson is the one worth putting in the report: *a constant latency across
unrelated endpoints is a property of the measurement, not the system.*

**2. `schema_linking_recall` was called with the wrong shape and order.**
It takes two flat lists as `(retrieved, gold)`; it was being handed
lists-of-lists in the opposite order. Caught immediately by the first ablation
run, which crashed rather than quietly returning a wrong number - the better
of the two failure modes.

**3. Recall was being pooled across questions rather than averaged.**
Pooling lets a question needing four tables outweigh one needing two. Now a
mean of per-question recall.

**4. Role assumptions in tests were order-dependent.**
The first account registered against a database becomes admin, so whether the
shared `auth_headers` fixture was privileged depended on test ordering. Every
role-sensitive test now states the role it wants.

---

## Milestone gate

The proposal's gate for this phase is the benchmark numbers themselves.
**Not met, and it cannot be met in this environment.**

What is met: every piece of machinery those numbers require is built, tested
and wired to the production code path. The remaining gap is one API key and
two dataset downloads, not any further engineering.

Delivered beyond the gate, and reportable as findings in their own right:

- A schema-linking ablation with a real, honestly-qualified result, including
  its own refusal to be over-read.
- A measured concurrency ceiling (~8.5 req/s) with a diagnosed structural
  cause.
- An error taxonomy ready to run over the first real benchmark output.

---

## Before Phase 7

1. **Set `ANTHROPIC_API_KEY`**, then
   `python -m evaluation.runner --dataset custom --predictor pipeline --save`.
   That single command produces the first accuracy figure this project has
   ever had.
2. **Download Spider** into `backend/evaluation/data/spider/`. Re-run
   `--ablation` against it; the discriminative-power guard should go quiet,
   and research question 1 gets a real answer.
3. Docker → Postgres, then re-run the load test to confirm the write
   serialisation is what caps throughput.
4. Run an accessibility checker before claiming an accessibility pass.
