# Progress & Handoff

Continuation notes for the **AI-Based Natural Language Query Processing and
Data Analytics Platform** capstone ([`proposal.md`](proposal.md)).

Written so a new session can pick this up cold. Read this file, then
[`docs/phase-3.md`](docs/phase-3.md) for the most recent detail.

**Status: Phases 0–3 complete. Phase 4 is next.**

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

**344 backend tests pass.** ruff clean, frontend builds clean.

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

---

## 6. Layout

```
backend/app/
  api/v1/          auth.py  connections.py  health.py  query.py
  core/            config  crypto  database  logging  security
  models/          user  connection  query  schema_index  audit
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
                   pipeline.py      — THE ORCHESTRATOR (generate→validate→execute)
                   generator.py     — session history + few-shot lookups only
    validation/    gates.py         — the four gates
    execution/     runner.py        — sandboxed execution, EXPLAIN
    analytics/     EMPTY — Phase 4 goes here
  workers/         EMPTY — Celery, Phase 6
backend/evaluation/  datasets  metrics  runner (predictor slot still a stub)
frontend/src/
  api/             typed client (client, auth, health, connections, query)
  components/      AppShell  ui.tsx  icons.tsx  SqlBlock  ResultTable
                   SchemaExplorer  AddConnectionForm  HealthBadge
  pages/           LoginPage  ConnectionsPage  AskPage
  stores/          authStore  themeStore
docs/              phase-0.md … phase-3.md
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

---

## 8. Known gaps

**Blocking real results:**
1. No API key → **no accuracy has ever been measured**. Phase 2's ≥65% and
   Phase 3's ≥75% gates are unmet and unmeasurable.
2. Spider/BIRD not downloaded.
3. Harness predictor slot is still the placeholder stub — `pipeline.run` is
   not wired into it.

**Written but never executed:**
4. Anthropic client (no live call ever made).
5. Postgres/MySQL: introspection, execution, session guards, `pgvector`.
6. Docker Compose stack.
7. Statement timeout (no test forces a slow enough query).

**Scoped but not built:**
8. **Redis result caching** — was Phase 3 scope, deferred rather than
   half-built.
9. `EXPLAIN`-based cost estimation — `explain()` exists and is tested, but
   the cost gate only enforces a row cap.
10. OpenAI GPT-5 as secondary provider (A/B + failover).
11. Retrieval at scale — demo schema has 8 tables; nothing establishes recall
    at 400.

---

## 9. Remaining phases

### Phase 4 — Analytics & Visualization (weeks 10–11)

Build in `services/analytics/` (currently empty).

- **F14 Statistical profiling** — row count, column types, cardinality, null
  density. Pandas/NumPy already in `requirements.txt`.
- **F11 Chart selection** — rule-based from result shape: time column → line;
  one categorical ≤15 values → bar; two numerics → scatter; single scalar →
  KPI card; else table.
- **F12 Manual chart override** — user switches type, axes, aggregation.
- **F15 Outlier detection** — IQR and z-score, visually highlighted.
- **F16 Trend analysis** — period-over-period deltas, growth rates, moving
  averages.
- **F13 Narrative insight** — pass profile + data sample to the LLM for a
  2–3 sentence summary. *Add PII masking before the sample leaves the box —
  the proposal lists this under the security model.*
- **F17 Export** — CSV, Excel, JSON, PNG, PDF.
- **F18 Dashboard builder** — pin queries, refresh on open.

Frontend needs Recharts (`npm i recharts`) — not yet installed. The Stitch
design system has a Dashboards screen already designed; the nav item is
stubbed with a `P4` badge in `AppShell.tsx`.

**Also do here:** the Redis cache deferred from Phase 3.

*Deliverable: every query returns a table, an appropriate chart, and a
written summary.*

### Phase 5 — Conversation & Learning (weeks 12–13)

- **F19 Multi-turn** — coreference resolution exists in `intent.py`; extend
  and test it harder.
- **F20 Ambiguity clarification** — exists; extend to targeted questions
  rather than one generic prompt.
- **F21 Query explanation panel** — the generation already returns an
  explanation; build the walkthrough UI.
- **F22 Learning from corrections** — user-edited SQL stored and retrieved as
  few-shot examples. **Wiring exists**: `generator._few_shot_examples()` is a
  one-function swap from "most recent successes" to embedding-similarity
  selection. Needs the `corrections` table from Appendix C.
- **F23 Suggested questions** — schema-aware starters on connect (the Ask
  page has hardcoded ones now).
- **F24 Business glossary** — map "active user", "churn" to SQL definitions.
- **F25 Semantic caching** — serve cached results for semantically equivalent
  questions.

### Phase 6 — Hardening & Evaluation (weeks 14–15)

**This is where the numbers come from. It is the highest-risk phase.**

- Wire `pipeline.run` into the harness predictor slot.
- Download Spider, Spider-Realistic, BIRD.
- Full benchmark runs with a real API key.
- **Ablation study**: no-retrieval vs retrieval; no-FK-expansion vs
  expansion; no-correction vs correction; zero-shot vs few-shot; Claude vs
  GPT. The retrieval and correction ablations directly answer research
  questions 1 and 2.
- Error taxonomy over failures (wrong table/column/join/aggregation/filter/
  ordering, ambiguous, unanswerable).
- Load testing, RBAC (`require_roles` exists, unused), audit logging (model
  exists, written to), cost/token tracking, accessibility pass.
- Compare local hashing embedder vs `text-embedding-3-small` on
  schema-linking recall — decides whether the local fallback is viable.

### Phase 7 — Presentation (week 16)

Final report, slide deck, demo video, live demonstration.

**For the report — be honest about these:**
- `temperature=0` is not achievable on current models (§7 above).
- Which embedder produced each number.
- The stub-vs-real distinction in any measurement.
- Docker/Postgres/pgvector paths that were never exercised.

---

## 10. Immediate next steps

1. **Set `ANTHROPIC_API_KEY`** in `backend/.env`. This unblocks more than
   anything else — first live Anthropic call, first real translation, first
   measurable accuracy, and the correction recovery rate for research
   question 2.
2. **Install Docker Desktop**, bring up
   `docker/docker-compose.yml`, and re-run the suite against Postgres. Needed
   before any claim about pgvector or the 200-table indexing milestone.
3. **Start Phase 4** in `services/analytics/`.

None of these blocks the others. (1) gives you real numbers; (2) closes the
biggest unverified surface; (3) is the next feature phase.

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
