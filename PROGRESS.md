# Progress & Handoff

Continuation notes for the **AI-Based Natural Language Query Processing and
Data Analytics Platform** capstone ([`proposal.md`](proposal.md)).

Written so a new session can pick this up cold. Read this file, then
[`docs/phase-6.md`](docs/phase-6.md) for the most recent detail.

**Status: Phases 0–7 complete.** Report, deck and demo runbook are in
`docs/`.

**The evaluation machinery is finished and has never produced an accuracy
figure, because there is still no `ANTHROPIC_API_KEY`. One environment
variable now stands between this project and its first real number.**

---

## 1. What this project is

A web platform where a user types a question in plain English against a live
relational database and gets back validated SQL, a result table, a chart, and
a written summary.

The contribution is not the LLM call — it is the surrounding pipeline: schema
linking that scales past the context window, a validation layer that catches
hallucinated identifiers before execution, a self-correction loop driven by
database error messages, and a safety model that makes the system safe to
point at a production replica.

---

## 2. How to run it

```bash
cd backend && python -m venv .venv && .venv/Scripts/python -m pip install -r requirements-dev.txt
```

```bash
cd backend && .venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` to port 8000. The first
account registered becomes admin.

Build the demo target database (8-table e-commerce schema, 2,000 orders):

```bash
cd backend && .venv/Scripts/python -m scripts.seed_demo_db
```

It prints a path. In the app: **Add connection** → **SQLite (file)** → paste
the path → **Test** → **Index schema** → then **Ask**.

**Verification — CI runs exactly these:**

```bash
cd backend && .venv/Scripts/python -m pytest
```

```bash
cd backend && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .
```

```bash
cd frontend && npm run lint && npm run build
```

---

## 3. Environment constraints (these shaped many decisions)

| Constraint | Consequence |
|---|---|
| **No `ANTHROPIC_API_KEY`** | Pipeline falls back to a stub that returns `SELECT * FROM <first table> LIMIT 10` without reading the question. **No accuracy figure has ever been measured.** |
| **No Docker** | Postgres, pgvector, and Redis have never run. App uses SQLite; embeddings stored as JSON. |
| **Python 3.10.9** (proposal says 3.11+) | Code is 3.10-compatible; Docker image pins 3.11. |
| **Spider/BIRD not downloaded** | Only the committed 10-question custom set is available to the harness. |
| **No Pandas/NumPy** | Despite what an earlier draft of this file said, they were never installed. Phase 4 profiling uses the stdlib `statistics` module instead — a deliberate deviation from the proposal's stack, documented in [`docs/phase-4.md`](docs/phase-4.md). |

Everything above is written and wired but unexercised. None of it is a
blocker for Phase 4 except where noted.

---

## 4. Commits

| Commit | Phase |
|---|---|
| `5280903` | 0 — Foundation: repo, CI, auth, health, eval harness |
| `cd4b52d` | 1 — Connection manager, schema introspection, searchable index |
| `e1ea432` | UI rebuild on the Stitch design system |
| `b639206` | 2 — NL→SQL core: intent, hybrid retrieval, generation |
| `a9d3f05` | 3 — Validation gates, sandboxed execution, self-correction |
| `d1330b8` | 4 — Analytics, visualization, dashboards, result cache |
| `ebc8a36` | 5 — Conversation, corrections, glossary, semantic cache |
| `f7a5ed2` | 6 — Evaluation harness, ablations, taxonomy, RBAC, usage |
| _this_ | 7 — Final report, slide deck, demo runbook |

**547 backend tests pass.** ruff clean, frontend builds and lints clean.

---

## 5. What exists, by phase

### Phase 0 — Foundation ✅

FastAPI + SQLAlchemy 2.0 backend, React 19 + TypeScript + Vite frontend,
JWT auth with bcrypt and a `require_roles` factory, health endpoint probing
database and Redis separately, Alembic migrations, GitHub Actions CI, Docker
Compose (pgvector + Redis + backend + sample DB, **never run**), and the
evaluation harness (Spider/BIRD/custom loaders, section-9 metrics, CLI
runner).

### Phase 1 — Connection & Schema Layer ✅

- **Credentials**: Fernet-encrypted at rest, never logged, never returned by
  the API.
- **Introspection**: tables, columns, types, PK/FK, indexes, row estimates,
  sample values — all through SQLAlchemy's dialect-agnostic `Inspector`, so
  one code path serves Postgres, MySQL, and SQLite.
- **Descriptions**: deterministic templates naming join paths and known
  values, with abbreviations expanded (`cust_ref_id_v2` → "customer reference
  identifier v2"). This is the text that gets embedded.
- **Embeddings**: provider interface — OpenAI `text-embedding-3-small` when a
  key exists, local hashing vectorizer otherwise.
- **FK graph**: undirected adjacency, one-hop expansion, shortest join paths.
- **UI**: connections page with add/test/index and a schema explorer.

### Phase 2 — NL→SQL Core ✅ (never run against a live model)

- **Intent analyzer**: rule-based classification (aggregation, comparison,
  trend, ranking, filter, ambiguous), follow-up resolution against session
  history, relative-date expansion, explicit-limit extraction, clarifying
  questions for genuinely vague input.
- **Hybrid retrieval**: dense cosine + BM25, fused with reciprocal rank
  fusion, then expanded one hop along foreign keys.
- **Prompt builder**: retrieved subgraph rendered as `CREATE TABLE` DDL with
  keys, row estimates and low-cardinality sample values; per-dialect rules;
  join paths; resolved time windows; few-shot examples. Same builder produces
  the repair prompt.
- **LLM layer**: Anthropic client (written, **never called live**), a
  deterministic stub, and a scripted test double.
- **UI**: Ask workspace with SQL highlighting and a "How this was built"
  provenance panel.

### Phase 3 — Validation, Safety & Execution ✅

- **Four gates** (`services/validation/gates.py`) on sqlglot: syntax →
  safety → schema → cost. Safety runs before schema deliberately.
- **Sandboxed execution**: SQLite opens through a `mode=ro` URI so the driver
  refuses writes; Postgres/MySQL get read-only sessions and statement
  timeouts (**written, never run**). Rows capped by reading one past the
  limit so truncation is reported.
- **Self-correction loop** (`services/generation/pipeline.py`): generate →
  validate → execute, feeding errors back up to 3 attempts. **Safety
  rejections never retry.**
- **API**: `POST /query` runs the whole pipeline; `POST /query/execute` runs
  user-edited SQL through identical gates.
- **UI**: sortable/paginated result table, rejection panel naming the gate,
  "repaired after N attempts" note.

**Milestone gate met**: 43 of 43 adversarial cases blocked, all as hard
rejections, plus independent confirmation that the connection itself refuses
writes.

### Phase 4 — Analytics & Visualization ✅ (narrative LLM path never run)

- **Profiling** (F14): type inference from *values*, not declared types —
  SQLite returns dates as strings. Every column records how it was classified.
  Chart selection, outliers and trends all read the profile, never the rows.
- **Chart selection** (F11): ordered rules, first match wins, each carrying
  the sentence that produced it. Table is the floor — never wrong, only less
  illuminating.
- **Manual override** (F12): type and axis pickers, populated from the same
  profile so the two cannot disagree about what counts as a category.
- **Outliers** (F15): IQR *and* z-score, with which methods agreed reported.
- **Trends** (F16): least-squares direction, deltas, growth rates, trailing
  moving average. Declines with a reason when the result is not a series.
- **PII masking**: column-name *and* value-pattern detection, applied at the
  boundary — including the profile's own sample values, which is where the
  first implementation leaked.
- **Narrative** (F13): the model gets exact statistics plus 20 masked rows,
  never raw data to add up. `TemplateNarrator` writes a real summary offline.
- **Export** (F17): CSV/JSON/XLSX/PDF server-side; PNG from the browser's own
  SVG.
- **Dashboards** (F18): tiles store validated SQL, re-validated and re-run on
  every open. One broken tile does not fail the refresh.
- **Result cache**: Redis or in-process, keyed on validated SQL, `cached: true`
  on every hit so no benchmark can misread it.

**Milestone gate met**: every query returns a table, an appropriate chart, and
a written summary — confirmed in the running app.

### Phase 5 — Conversation & Learning ✅ (every prompt change is unmeasured)

Everything here is about the system knowing what the schema does not.

- **Multi-turn** (F19): pronoun *and* elliptical follow-ups, merged into one
  instruction rather than two glued sentences, with context accumulating
  across a chain of turns.
- **Clarification** (F20): names what is missing and offers clickable
  rewrites. Deliberately does *not* refuse more questions than before.
- **Explanation** (F21): clause-by-clause walkthrough read from the parsed
  SQL, shown beside the model's own prose so a divergence is visible.
- **Corrections** (F22): few-shot examples chosen by similarity, with
  corrections outranking successes. A correction is stored only after it
  passes the gates and executes.
- **Suggestions** (F23): starters generated from the indexed schema.
- **Glossary** (F24): literal term matching, injected into the prompt.
- **Semantic cache** (F25): skips generation for a question already answered
  in different words — behind a 0.93 threshold, polarity guards, and full
  visibility in the UI.

**Caveat for the report**: this phase changes prompts, and prompt quality
cannot be measured without a model. Every feature is a mechanism whose effect
is unmeasured.

### Phase 6 — Hardening & Evaluation ✅ (machinery complete, no accuracy yet)

- **Predictor slot filled**: `pipeline.run` is wired into the harness, with
  ablation knobs threaded through the production code path rather than
  reimplemented.
- **Gold tables** parsed from benchmark SQL with sqlglot — a regex would
  inflate recall by missing joins and counting CTE names.
- **Error taxonomy**: ordered wrong_table → wrong_join → wrong_aggregation →
  wrong_filter → wrong_column → wrong_ordering, most fundamental first.
- **Ablation study, with real numbers** — and a `discriminates()` guard that
  declares the current result non-discriminative, which it is: the 8-table
  demo schema is saturated at 98% coverage. FK expansion helps consistently
  (+2.5 recall, +10 all-found); hybrid fusion shows no benefit at this scale.
- **Load test**: 200/200 succeed at 20-way concurrency, but throughput is flat
  at ~8.5 req/s while latency grows linearly — complete serialisation on
  SQLite's single writer.
- **RBAC**: `require_roles` finally used, gating the audit trail.
- **Usage endpoint** (Appendix B): tokens, estimated cost, per-user breakdown
  for admins, with the rate table returned alongside.

---

## 6. Layout

```
backend/app/
  api/v1/          auth.py  connections.py  dashboards.py  health.py
                   learning.py  query.py  usage.py
  core/            config  crypto  database  logging  security
  models/          user  connection  query  schema_index  audit  dashboard
                   learning (corrections, glossary)
  schemas/         Pydantic contracts
  services/
    connection/    manager.py       — URLs, credentials, engines
    introspect/    introspector.py  — schema extraction
                   describe.py      — NL descriptions (embedded text)
    linking/       embeddings.py    — provider interface + local fallback
                   graph.py         — FK graph, one-hop expansion
                   indexer.py       — introspect → describe → embed → store
                   retriever.py     — dense + BM25 + RRF + expansion
    generation/    intent.py        — classification, coreference, dates
                   prompts.py       — DDL rendering, dialect rules
                   llm.py           — Anthropic / stub / scripted
                   explain.py       — SQL → clause-by-clause English (F21)
                   pipeline.py      — THE ORCHESTRATOR (generate→validate→execute)
                   generator.py     — session history + few-shot lookups only
    validation/    gates.py         — the four gates
    execution/     runner.py        — sandboxed execution, EXPLAIN
    analytics/     profile.py       — type inference + descriptive stats (F14)
                   charts.py        — rule-based chart selection (F11/F12)
                   outliers.py      — IQR + z-score (F15)
                   trends.py        — deltas, growth, moving average (F16)
                   masking.py       — PII masking on the outbound path
                   narrative.py     — LLM summary + offline template narrator (F13)
                   export.py        — CSV / JSON / XLSX / PDF (F17)
                   analyze.py       — composes the four local steps
    cache/         store.py         — Redis / in-process / null backends
                   results.py       — cached execution, invalidation
                   semantic.py      — question-level cache, skips generation (F25)
    learning/      corrections.py   — similarity-selected examples (F22)
                   suggestions.py   — schema-aware starters (F23)
                   glossary.py      — business term matching (F24)
  workers/         EMPTY — Celery, Phase 6
backend/evaluation/  datasets  metrics  runner
                   gold.py       — gold-table extraction (sqlglot)
                   harness.py    — throwaway indexed DB per run
                   predictors.py — pipeline.run wired in (slot now filled)
                   taxonomy.py   — how a wrong answer is wrong
                   ablations.py  — retrieval ablation + discriminative guard
backend/scripts/     seed_demo_db  load_test
frontend/src/
  api/             typed client (client, auth, health, connections, query,
                   analytics, dashboards, learning)
  components/      AppShell  ui.tsx  icons.tsx  SqlBlock  ResultTable
                   SchemaExplorer  AddConnectionForm  HealthBadge
                   ChartView  ChartControls  ProfilePanel  InsightPanel
                   ExportMenu  PinToDashboard  ResultView
                   ExplanationPanel  CorrectionEditor
  pages/           LoginPage  ConnectionsPage  AskPage  DashboardsPage
                   GlossaryPage
  stores/          authStore  themeStore
docs/              phase-0.md … phase-6.md
                   final-report.md  slides.md  demo-script.md
```

**`pipeline.run()` is the single entry point** for answering a question.

---

## 7. Decisions already made — do not re-litigate

| Decision | Why |
|---|---|
| **`temperature=0` is impossible** | Sampling params return 400 on Claude Sonnet 5 and every current frontier model. The proposal claims it as a design property; **this must be corrected in the final report.** Determinism comes from prompt + `effort`. |
| **Structured output, not prefill** | Assistant prefill is rejected on current models. Uses `output_config.format` with a JSON schema — response is guaranteed to parse. |
| **Intent analysis is rule-based** | The proposal budgets 300 ms; an LLM round trip cannot meet it. Wrong label degrades quality, not correctness. |
| **RRF, not score normalization** | Cosine and BM25 are on different scales; calibrating them is fragile. RRF reads only rank position. |
| **Safety before schema** | Otherwise `DROP TABLE misspelled` returns as a retryable schema error and re-enters the loop. |
| **Safety failures never retry** | Retrying a DROP turns one blocked write into three requests for the same forbidden thing. Asserted on every adversarial case. |
| **SQLite added as a target dialect** | Out of proposal scope, but introspection is dialect-agnostic so it cost nothing and made everything demonstrable without Docker. |
| **Descriptions are templates, not LLM-written** | 400 tables = 400 LLM calls, and non-determinism makes retrieval evaluation irreproducible. |
| **Local hashing embedder as fallback** | Lexical overlap only — will not match "revenue" to "sales". Honest dev infrastructure. `IndexResult` carries the embedder name so no run can be misreported. |
| **Stub provider rather than hard failure** | Pipeline/API/UI exercisable offline. Stub is loud: confidence 0, explicit assumption, model name `stub`. |
| **Manual SQL uses identical gates** | Hand-edited SQL is *less* trusted — it never passed through a prompt forbidding writes. |
| **Only executed queries become few-shot examples** | A valid query that failed at runtime teaches the wrong thing. |
| **Stdlib `statistics`, not Pandas/NumPy** | The proposal's stack names them; the honest cost/benefit did not justify a 50 MB dependency for ~100 lines of arithmetic over ≤10,000 rows, and type inference had to be hand-written regardless. **Must be stated in the final report.** |
| **Chart selection is rule-based, like intent** | Fully determined by result shape; an LLM call would cost more than the whole analytics stage, and a wrong choice is one click from fixed. |
| **The narrator is given statistics, not raw rows** | Every number in a summary traces to arithmetic this process did, not to a model's mental addition of a partial sample. |
| **PII masking applies at the boundary, not to one object** | Learned the hard way: the first implementation masked the sample rows but not the profile's own top values, and leaked names into the prompt. |
| **Dashboard tiles store SQL, not questions** | Re-asking on open would re-run generation, cost tokens each time, and could return a different query than the user pinned. |
| **Cached results are labelled `cached`** | A 2 ms cache hit reported as query latency would flatter every benchmark in the final report. |
| **F20 does not refuse more questions than before** | An earlier Phase 5 draft made "top 5 products" ambiguous for naming no measure; it broke two Phase 2 tests, and rightly. Phase 2 decided such questions get answered with the assumption stated. |
| **The explanation is parsed, not narrated** | The model's prose says what it meant; the parsed reading says what will run. Both are shown so a divergence is visible. |
| **A correction must execute before it is stored** | An unverified correction taught as an example propagates a mistake rather than fixing one. |
| **Glossary matching is literal, not semantic** | A definition applied because it was *nearly* relevant would change a query's meaning invisibly. |
| **Semantic cache: 0.93 plus polarity guards** | A question and its negation are neighbours in embedding space; similarity alone cannot separate them. |
| **Ablation knobs live in the retriever, not the harness** | A harness that reimplements retrieval measures the reimplementation. |
| **The ablation reports when it proves nothing** | The strongest possible result on a small schema is a table of 100%s that means nothing. `discriminates()` says so out loud. |
| **Costs are labelled estimates and ship with their rates** | `tokens_used` is a combined total split by assumption; a stored cost silently goes stale when prices move. |

---

## 8. Known gaps

**Blocking real results:**
1. No API key → **no accuracy has ever been measured**. Phase 2's ≥65% and
   Phase 3's ≥75% gates are unmet and unmeasurable. Phase 6 finished the
   machinery, so this is now the *only* thing in the way.
2. Spider/BIRD not downloaded. The loaders and gold-table extraction are
   ready; without them the ablation runs on an 8-table schema that cannot
   discriminate between retrieval methods.
3. ~~Harness predictor slot~~ — **done in Phase 6**; `pipeline.run` is wired
   in behind `--predictor pipeline`.

**Written but never executed:**
4. Anthropic client (no live call ever made) — now *two* of them: the SQL
   generator and Phase 4's `AnthropicNarrator`. Every narrative so far came
   from the template narrator. Phase 5 changed the prompt substantially
   (glossary, similarity-selected examples) and **none of it has reached a
   model**.
5. Postgres/MySQL: introspection, execution, session guards, `pgvector`.
6. Docker Compose stack.
7. Statement timeout (no test forces a slow enough query).
8. `RedisCache` — written in Phase 4, exercised only as `MemoryCache`.
9. **Multi-turn beyond two turns.** `docs/phase-5.md` claims a chain of
   follow-ups accumulates context. It does not: `_recent_questions` selects
   `Query.question`, the text as typed, so a third turn resolves against the
   raw second turn and loses the first. Two turns work correctly. Fixing it
   means persisting the resolved question — a column and a migration.
10. Cross-vocabulary semantic caching — the local embedder matches on word
   overlap, so "revenue" will never match "sales" until a real embedding
   provider is configured.
10. Embedder comparison (hashing vs `text-embedding-3-small`) — needs an
    `OPENAI_API_KEY` to have a second arm.
11. Accessibility — considered while building, never actually audited.
12. Concurrency beyond ~8.5 req/s — measured and diagnosed (SQLite single
    writer, one uvicorn worker), not fixed. Needs Postgres.

**Scoped but not built:**
8. `EXPLAIN`-based cost estimation — `explain()` exists and is tested, but
   the cost gate only enforces a row cap.
9. OpenAI GPT-5 as secondary provider (A/B + failover).
11. Retrieval at scale — demo schema has 8 tables; nothing establishes recall
    at 400.

---

## 9. Remaining phases

### Phase 4 — Analytics & Visualization (weeks 10–11) — ✅ DONE

See [`docs/phase-4.md`](docs/phase-4.md).

### Phase 5 — Conversation & Learning (weeks 12–13) — ✅ DONE

See [`docs/phase-5.md`](docs/phase-5.md).

### Phase 6 — Hardening & Evaluation (weeks 14–15) — ✅ DONE

See [`docs/phase-6.md`](docs/phase-6.md). The machinery is complete; the
numbers are not, and cannot be until an API key exists.

### Phase 7 — Presentation (week 16) — ✅ DONE

- [`docs/final-report.md`](docs/final-report.md) — the report
- [`docs/slides.md`](docs/slides.md) — 16 slides with speaker notes
- [`docs/demo-script.md`](docs/demo-script.md) — live runbook, likely
  questions, and what to do when something breaks

---

## 10. Immediate next steps

Phases 0–6 are complete. Everything below is blocked on the environment, not
on engineering.

1. **Set `ANTHROPIC_API_KEY`** in `backend/.env`, then:

   ```
   python -m evaluation.runner --dataset custom --predictor pipeline --save
   ```

   That one command produces the first accuracy figure this project has ever
   had, plus the correction recovery rate for research question 2 and an error
   taxonomy over the failures.

2. **Download Spider** into `backend/evaluation/data/spider/` and re-run
   `python -m evaluation.runner --ablation --save`. The 8-table demo schema is
   saturated and the harness says so; Spider's larger schemas are what make
   research question 1 answerable.

3. **Docker → Postgres + Redis.** Closes the largest unexercised surface and
   should lift the ~8.5 req/s ceiling the load test found.

4. **Phase 7**: the report. `docs/phase-*.md` carry the decisions, the bugs
   found, and — importantly — a "Not verified" section each, which is the
   honest backbone of the write-up.

---

## 11. Working agreement for the next session

Established in this project and worth keeping:

- **Stop at each phase boundary.** Complete a phase fully — including
  verification and a `docs/phase-N.md` write-up — commit, summarize, and
  wait. Do not roll into the next phase unattended.
- **Launch the app and show the result** after each phase.
- **Write down what was NOT verified**, in the phase doc and the summary. The
  running theme here is that plenty is written but unexercised; conflating
  the two would make the final report wrong.
- Every phase doc follows the same shape: What was built / Verified / Not
  verified / Decisions / Bugs found / Milestone gate / Before next phase.
