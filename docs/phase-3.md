# Phase 3 - Validation, Safety & Execution

Proposal weeks 8-9. Deliverable: *"zero successful write operations across the
adversarial test suite; accuracy lifted to ≥ 75% by self-correction."*

---

## What was built

**The four-gate validation engine** (`services/validation/gates.py`), on
`sqlglot`:

| Gate | Checks | On failure |
|---|---|---|
| Syntax | Parses for the target dialect | Retry with the error |
| Safety | Statement type, multi-statement, comments, dangerous functions, system catalogs, `SELECT … INTO` | **Hard reject - never retried** |
| Schema | Every table and column exists; aliases and CTEs resolve | Retry with a "did you mean" hint |
| Cost | Forces a row cap, lowering an over-large `LIMIT` | Rewrite, warn the user |

Safety runs *before* schema, so `DROP TABLE nonexistent` is rejected as
unsafe rather than returned as a retryable schema error.

**Sandboxed execution** (`services/execution/runner.py`). Postgres and MySQL
sessions are opened read-only with a server-enforced statement timeout;
SQLite is opened through a `mode=ro` URI so the driver itself refuses writes.
Rows are capped by reading one past the limit, so a truncated result is
reported as truncated rather than silently short. Driver errors are reduced
to the database's own sentence - "no such column: cust_name" - because that
is what the correction loop reads.

**The self-correction loop** (`services/generation/pipeline.py`). Generate →
validate → execute, feeding failures back up to three attempts. Safety
rejections end the loop immediately.

**API.** `POST /api/v1/query` now runs the whole pipeline and returns rows.
`POST /api/v1/query/execute` runs user-edited SQL through the *identical*
gates.

**UI.** A sortable, paginated result table with truncation and timing
reported; blocked queries render a distinct rejection panel naming the gate;
repaired queries say so.

---

## Verified

- **344 backend tests pass.** ruff and the frontend build are clean.
- **The adversarial suite blocks 43 of 43 cases** - writes, piggy-backed
  statements, comments, timing functions, system catalogs, `SELECT … INTO`,
  and writes buried in CTEs and subqueries - and every one is a *hard*
  rejection, asserted explicitly so none can re-enter the correction loop.
- **The database refuses writes on its own.** `test_execution.py` bypasses
  the gates entirely and fires writes straight at the connection; all are
  rejected by the driver, and the row count is unchanged afterwards.
- **No false positives**: a parallel corpus of legitimate queries - joins,
  CTEs, aggregates, `HAVING` - all pass.
- Driven live in the browser: nine attacks blocked with `orders` still at
  2,000 rows; a three-table "top N by revenue" query executed correctly; the
  cost gate applied a 10,000-row cap and said so.

## Not verified

- **The accuracy half of the gate.** ≥ 75% after self-correction cannot be
  measured without an `ANTHROPIC_API_KEY` - the stub does not read the
  question, so there is nothing to correct. The loop's *mechanism* is tested
  with scripted failures; the *recovery rate* is unmeasured.
- **Postgres and MySQL execution.** The session guards
  (`SET TRANSACTION READ ONLY`, `statement_timeout`,
  `MAX_EXECUTION_TIME`) are written but have never run - no server available.
  Only the SQLite path is exercised.
- **The statement timeout.** No test forces a query slow enough to trip it.
- **Redis caching** was in the phase scope and is **not built**. The proposal
  wants a result cache keyed on the normalised query hash; nothing here does
  that. Deferred rather than half-built.
- **`EXPLAIN`-based cost estimation.** `explain()` exists and is tested, but
  the cost gate only enforces a row cap - it does not yet block a plan whose
  estimated scan exceeds a threshold.

---

## Decisions

**Retryable versus hard reject is the loop's central distinction.** A
hallucinated column is a mistake the model can fix from the error message; an
attempted `DROP` is not a mistake to repair. Retrying it would turn one
blocked write into three requests for the same forbidden thing. The
adversarial suite asserts non-retryability on every case, not just blocking.

**Safety is checked before schema.** Otherwise a write against a misspelled
table returns as a retryable schema error and re-enters the loop.

**Comments are rejected outright.** They are how an injected statement
terminates the rest of a query, and no legitimate generated query needs one.
`sqlglot` strips them during parsing, so the raw string is checked separately.

**SQLite opens read-only via `mode=ro`.** SQLite has no roles to grant, so
this is the equivalent of the SELECT-only database user the other dialects
use - and it is a genuine driver-level guarantee, not a session hint.

**Driver errors are stripped before feedback.** SQLAlchemy wraps the
database's message in its own text, the echoed SQL, and a docs link. The
database's sentence is the repair signal; the rest dilutes it.

**The schema gate emits "did you mean" hints.** The proposal observes that
database errors are strong repair signals partly because they carry these.
The gate produces its messages in the same shape so a validation failure
repairs as readily as an execution one.

**Manual SQL goes through identical gates.** A hand-edited query is not more
trusted than a generated one - if anything less, since it never passed
through a prompt that forbade writes.

**Only executed queries become few-shot examples.** A syntactically valid
query that failed at runtime would teach the model the wrong thing.

---

## Bugs found during verification

**Select aliases were rejected as missing columns.** `SELECT COUNT(*) AS n …
ORDER BY n` - valid SQL, and the shape almost every "top N by revenue"
question produces - failed the schema gate. This would have caused false
rejections on a large fraction of legitimate queries and depressed any
accuracy measurement. Found by running a real aggregate through the live API,
not by the unit tests, which had only used real column names. Fixed and
pinned with four regression tests, including one asserting the allowance did
not become a blanket amnesty.

**`generator.run` was left dead** after the pipeline superseded it - two
near-identical orchestrators, one unreachable. Removed; `generator.py` now
holds only the session-history and few-shot lookups the pipeline uses.

---

## Milestone gate

> Week 9 - Safe execution verified - *adversarial suite fully blocked.*

**Met.** 43 of 43 adversarial cases blocked, all as hard rejections, plus
independent confirmation that the connection itself refuses writes.

The accuracy half of the phase deliverable (≥ 75% via self-correction) is
**not met and not measurable** without an API key.

---

## Before Phase 4

1. Set `ANTHROPIC_API_KEY`, then measure the correction recovery rate - this
   is the number research question 2 asks for.
2. Bring up Postgres and re-run the adversarial and execution suites against
   it; the session guards have never executed.
3. Build the Redis result cache deferred from this phase.
4. Add a slow-query test that actually trips the statement timeout.
