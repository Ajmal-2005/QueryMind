# AI-Based Natural Language Query Processing and Data Analytics Platform

**Capstone Project Proposal**

| Field | Value |
|---|---|
| Project Title | AI-Based Natural Language Query Processing and Data Analytics Platform |
| Domain | Natural Language Processing, Databases, Data Analytics |
| Primary Data Source | Relational databases (PostgreSQL / MySQL) |
| Core AI Approach | Hosted LLM APIs (OpenAI / Anthropic Claude) with schema-aware RAG |
| Duration | 16 weeks |
| Date | August 2026 |

---

## 1. Abstract

Business teams sit on top of relational databases they cannot query. Every question — "what were our top five products last quarter?" — has to be routed through an analyst who writes SQL, waits for it to run, and pastes the result into a chart. The bottleneck is not the data; it is the translation layer between human intent and SQL.

This project builds a web platform where a user types a question in plain English and receives a validated SQL query, a result table, an automatically chosen visualization, and a written summary of what the numbers mean. The system connects to a live PostgreSQL or MySQL database, extracts and indexes its schema, retrieves the relevant tables for a given question, and prompts a hosted large language model to generate SQL. Generated SQL is parsed, checked against the real schema, and executed read-only inside a sandbox before anything reaches the user.

The contribution is not the LLM call. It is the surrounding pipeline: schema linking that scales past the context window, a multi-stage validation layer that catches hallucinated columns before execution, a self-correction loop that repairs failed queries from the database's own error message, and a security model that makes the system safe to point at a production replica.

---

## 2. Problem Statement

Organizations store operational data in relational databases, but access to that data is gated behind SQL fluency. Three consequences follow.

**Analyst bottleneck.** Non-technical stakeholders queue behind a small data team. Simple questions take hours or days, so many are never asked.

**Existing BI tools are rigid.** Dashboards answer the questions someone anticipated at build time. Ad-hoc questions require a new dashboard, which requires an analyst — back to the bottleneck.

**Naive LLM approaches fail on real schemas.** Handing a schema to GPT and asking for SQL works on toy databases and breaks on real ones. Production schemas have hundreds of tables, cryptic column names (`cust_ref_id_v2`), undocumented join paths, and business logic embedded in conventions no model can infer. On the Spider benchmark, straightforward prompting reaches roughly 70% execution accuracy; on the harder BIRD benchmark, which uses realistic dirty schemas, the same approaches drop below 50%. The gap between those two numbers is the engineering problem this project addresses.

### Research Questions

1. How much does retrieval-based schema linking improve SQL generation accuracy on schemas too large to fit in a prompt?
2. Can a self-correction loop driven by database error messages recover a meaningful fraction of initially failed queries?
3. What validation layers are necessary before it is safe to execute LLM-generated SQL against a live database?

---

## 3. Objectives

**Primary**

1. Translate natural language questions into executable, correct SQL for PostgreSQL and MySQL.
2. Reach ≥ 80% execution accuracy on the Spider development set and ≥ 55% on BIRD.
3. Guarantee that no generated query can modify, delete, or exfiltrate data.
4. Return an answer — table, chart, and narrative summary — in under 8 seconds at the 95th percentile.

**Secondary**

5. Support multi-turn conversation, so "and break that down by region" resolves against the previous question.
6. Automatically select an appropriate chart type from the shape of the result set.
7. Explain every generated query in plain English so users can judge whether to trust it.
8. Learn from corrections: when a user fixes a query, store the pair and retrieve it for similar future questions.

---

## 4. System Architecture

### 4.1 High-Level Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                      PRESENTATION LAYER                          │
│   React + TypeScript  ·  Chat UI  ·  Charts  ·  SQL Editor      │
└───────────────────────────┬─────────────────────────────────────┘
                            │  REST + WebSocket (streaming)
┌───────────────────────────▼─────────────────────────────────────┐
│                      APPLICATION LAYER                           │
│                    FastAPI  ·  Auth  ·  Rate Limiting            │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                     NL → SQL CORE PIPELINE                       │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │  Intent  │→ │  Schema  │→ │   SQL    │→ │Validation│        │
│  │ Analyzer │  │  Linker  │  │Generator │  │  Engine  │        │
│  └──────────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘        │
│                     │              │             │               │
│                ┌────▼─────┐   ┌────▼─────┐  ┌────▼─────┐       │
│                │ pgvector │   │ LLM API  │  │ sqlglot  │       │
│                │  schema  │   │ (Claude/ │  │  parser  │       │
│                │  index   │   │  GPT)    │  │          │       │
│                └──────────┘   └──────────┘  └──────────┘       │
│                                                  │               │
│                            ┌─────────────────────▼───────────┐  │
│                            │  Self-Correction Loop (max 3)   │  │
│                            └─────────────────────┬───────────┘  │
└──────────────────────────────────────────────────┼──────────────┘
                                                   │
┌──────────────────────────────────────────────────▼──────────────┐
│                       EXECUTION LAYER                            │
│   Read-only connection pool  ·  Query timeout  ·  Row limits    │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                    ANALYTICS & INSIGHT LAYER                     │
│   Pandas profiling  ·  Chart selection  ·  LLM summarization    │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                        DATA LAYER                                │
│   User's PostgreSQL/MySQL (read-only)  ·  App Postgres +         │
│   pgvector  ·  Redis cache                                       │
└──────────────────────────────────────────────────────────────────┘
```

### 4.2 Component Responsibilities

**Intent Analyzer.** Classifies the question — aggregation, comparison, trend, ranking, filter, or ambiguous. Resolves pronouns and ellipsis against conversation history ("break *that* down by region"). Flags questions too vague to answer and generates a clarifying question instead of guessing.

**Schema Linker.** The component that determines whether the system works on real databases. At connection time it introspects the target database: tables, columns, types, primary and foreign keys, indexes, and a sample of distinct values per low-cardinality column. Each table becomes a natural-language description ("`orders` — one row per customer purchase; joins to `customers` via `customer_id`") which is embedded and stored in pgvector. At query time it retrieves the top-k relevant tables by hybrid search (dense embeddings + BM25 keyword match), then expands the set by following foreign keys one hop out so join paths are never missing. Only that subgraph enters the prompt — the difference between a 400-table schema and a 6-table prompt.

**SQL Generator.** Constructs a prompt containing the retrieved schema subgraph, dialect rules, few-shot examples selected by similarity to the current question, and the conversation context. Requests structured output: the SQL, a confidence score, a plain-English explanation, and any assumptions the model made. Runs at temperature 0 for determinism.

**Validation Engine.** Four gates, all before execution.

| Gate | Check | Failure action |
|---|---|---|
| Syntax | Parse with `sqlglot` for the target dialect | Regenerate |
| Schema | Every table and column exists; joins follow real FK paths | Regenerate with error fed back |
| Safety | Reject `INSERT`/`UPDATE`/`DELETE`/`DROP`/`ALTER`/`GRANT`, multi-statement, comments, `pg_sleep`, system catalogs | Hard reject, no retry |
| Cost | `EXPLAIN` the plan; block full scans over a threshold; force `LIMIT` | Rewrite with limit, warn user |

**Self-Correction Loop.** When a query fails validation or execution, the error message, the failed SQL, and the original question are sent back to the model for repair. Capped at three attempts; each attempt is logged for the evaluation. The database's own error messages are precise ("column `cust_name` does not exist, perhaps you meant `customer_name`") and turn out to be strong repair signals.

**Execution Layer.** A dedicated read-only database role with `SELECT`-only grants — the last line of defense, independent of anything the LLM does. Statement timeout of 30 seconds, hard row cap of 10,000, connection pooling, and a Redis cache keyed on the normalized query hash.

**Analytics & Insight Layer.** Profiles the result set (row count, column types, cardinality, null density) and selects a visualization by rule: time column present → line chart; one categorical dimension with ≤ 15 values → bar; two numerics → scatter; single scalar → KPI card; anything else → table. Computes descriptive statistics, detects outliers with IQR, and passes the profile plus a data sample to the LLM for a two-to-three sentence narrative summary.

---

## 5. Request Workflow

**Example:** *"Which product categories grew the most in revenue last quarter compared to the previous one?"*

| # | Stage | What happens | Budget |
|---|---|---|---|
| 1 | Ingest | Question + session ID + connection ID received over WebSocket | 10 ms |
| 2 | Cache | Hash normalized question; on hit, return cached result | 20 ms |
| 3 | Intent | Classified as comparison + trend; two time windows detected; no ambiguity | 300 ms |
| 4 | Schema link | Retrieves `orders`, `order_items`, `products`, `categories`; FK expansion adds `product_categories` | 150 ms |
| 5 | Generate | LLM returns SQL with two CTEs, a self-join on quarter, and a growth-percentage column | 2–4 s |
| 6 | Validate | Syntax OK · all identifiers exist · read-only · `EXPLAIN` cost acceptable | 200 ms |
| 7 | Execute | Read-only pool, 30 s timeout, 12 rows returned | 400 ms |
| 8 | Analyze | Categorical + numeric shape → grouped bar chart; growth outliers flagged | 250 ms |
| 9 | Summarize | "Home & Garden led growth at +34%, driven by outdoor furniture. Electronics declined 8%, the only category to shrink." | 1–2 s |
| 10 | Deliver | Streamed to the UI: SQL, table, chart, summary, and an explanation panel | — |
| 11 | Feedback | Thumbs up/down; a correction is stored as a new few-shot example | — |

**Total: 4–8 seconds.** Steps 5 and 9 dominate and both stream token-by-token, so the user sees SQL appearing within roughly a second.

**Failure path.** If step 6 or 7 fails, the loop returns to step 5 with the error appended. After three failed attempts the system shows the best attempt, the error, and an editable SQL box rather than an unhelpful "I couldn't answer that."

---

## 6. Feature Specification

### 6.1 Core Features (Must Have — Phases 1–3)

| ID | Feature | Description | Acceptance criteria |
|---|---|---|---|
| F1 | NL → SQL translation | English question to executable SQL | ≥ 80% execution accuracy on Spider dev |
| F2 | Database connection manager | Add/test/manage Postgres & MySQL connections; encrypted credentials | Connect and introspect in < 30 s for a 200-table schema |
| F3 | Automatic schema introspection | Extract tables, columns, types, keys, sample values | Full FK graph reconstructed |
| F4 | Schema-linked retrieval | Retrieve relevant subgraph via hybrid search | ≥ 95% recall of required tables |
| F5 | SQL validation pipeline | Syntax, schema, safety, and cost gates | 100% of write operations blocked |
| F6 | Read-only sandboxed execution | Dedicated role, timeout, row cap | Zero writes possible even if validation is bypassed |
| F7 | Result table | Sortable, paginated, filterable grid | Handles 10k rows without lag |
| F8 | SQL transparency panel | Show generated SQL with syntax highlighting | Always visible, never hidden |
| F9 | Self-correction loop | Repair failed SQL from error feedback | ≥ 40% of initial failures recovered |
| F10 | Query history | Persisted per user with re-run | Searchable |

### 6.2 Analytics Features (Should Have — Phase 4)

| ID | Feature | Description |
|---|---|---|
| F11 | Automatic chart selection | Rule-based choice from result shape (line/bar/pie/scatter/KPI/table) |
| F12 | Manual chart override | User switches type, axes, aggregation |
| F13 | Narrative insight generation | LLM writes a plain-English summary of what the numbers show |
| F14 | Statistical profiling | Descriptives, distributions, null analysis |
| F15 | Outlier detection | IQR and z-score flagging with visual highlight |
| F16 | Trend analysis | Period-over-period deltas, growth rates, moving averages |
| F17 | Export | CSV, Excel, JSON, PNG chart, PDF report |
| F18 | Dashboard builder | Pin queries to a saved dashboard; refresh on open |

### 6.3 Intelligence Features (Should Have — Phase 5)

| ID | Feature | Description |
|---|---|---|
| F19 | Multi-turn conversation | Follow-ups resolved against prior context |
| F20 | Ambiguity clarification | Ask a targeted question instead of guessing |
| F21 | Query explanation | Plain-English walkthrough of what the SQL does |
| F22 | Learning from corrections | User-edited SQL stored and retrieved as few-shot examples |
| F23 | Suggested questions | Schema-aware starter prompts on connection |
| F24 | Business glossary | Map organization terms ("active user", "churn") to SQL definitions |
| F25 | Semantic caching | Serve cached results for semantically equivalent questions |

### 6.4 Platform Features (Should Have — Phase 6)

| ID | Feature | Description |
|---|---|---|
| F26 | Authentication & RBAC | JWT auth; admin / analyst / viewer roles |
| F27 | Row-level security passthrough | Honor the underlying database's RLS policies |
| F28 | Audit logging | Every question, SQL, user, and timestamp recorded immutably |
| F29 | Cost & token tracking | Per-user LLM spend dashboard with quotas |
| F30 | Scheduled queries | Cron-scheduled runs with email delivery |

### 6.5 Stretch Features (Could Have — Phase 7 if time permits)

| ID | Feature | Description |
|---|---|---|
| F31 | Voice input | Whisper-based speech-to-query |
| F32 | Slack bot | Ask questions from Slack, get charts back |
| F33 | Anomaly alerting | Monitor a metric, alert on statistical deviation |
| F34 | Forecasting | Prophet/ARIMA projections on time series results |
| F35 | Local model fallback | Fine-tuned open-source model for common query patterns |

### 6.6 Explicit Non-Goals

Writing to the database. NoSQL and warehouse connectors. Real-time streaming data. A full BI replacement. Mobile-native apps. Multi-tenant SaaS billing. These are excluded to keep the capstone scope achievable; the architecture does not preclude them.

---

## 7. Technology Stack

### Frontend

| Component | Choice | Rationale |
|---|---|---|
| Framework | React 18 + TypeScript | Type safety across a large component surface |
| Build | Vite | Fast HMR |
| Styling | Tailwind CSS + shadcn/ui | Accessible components without design overhead |
| State | Zustand + TanStack Query | Lightweight client state, robust server-state caching |
| Charts | Recharts (primary), Plotly.js (advanced) | Recharts for standard charts, Plotly for interactivity |
| Tables | TanStack Table | Virtualized rendering for 10k rows |
| SQL editor | Monaco Editor | Syntax highlighting and manual editing |
| Streaming | Native WebSocket | Token-by-token LLM output |

### Backend

| Component | Choice | Rationale |
|---|---|---|
| Framework | FastAPI (Python 3.11+) | Async, auto OpenAPI docs, native Pydantic validation |
| ORM | SQLAlchemy 2.0 + Alembic | Dialect abstraction and migrations |
| Validation | Pydantic v2 | Contract enforcement on LLM structured output |
| SQL parsing | **sqlglot** | Multi-dialect AST parsing — the backbone of validation |
| Async jobs | Celery + Redis | Schema indexing, scheduled queries |
| Auth | JWT (python-jose) + passlib/bcrypt | Standard, stateless |
| Testing | pytest, pytest-asyncio, httpx | Unit and integration coverage |

### AI / NLP

| Component | Choice | Rationale |
|---|---|---|
| Primary LLM | Claude Sonnet 5 (Anthropic API) | Strong SQL generation, large context, reliable structured output |
| Secondary LLM | GPT-5 (OpenAI API) | A/B comparison and failover |
| Orchestration | LangChain (light use) | Prompt templating and retry logic only — no heavy abstraction |
| Embeddings | `text-embedding-3-small` (OpenAI) | Cheap, good enough for schema descriptions |
| Vector store | **pgvector** on Postgres | Avoids a separate vector DB; one system to operate |
| Keyword search | Postgres full-text (`tsvector`) | Hybrid retrieval partner to dense search |
| Reranking | Cohere Rerank (optional) | Precision boost on the retrieved table set |

### Data & Infrastructure

| Component | Choice | Rationale |
|---|---|---|
| App database | PostgreSQL 16 + pgvector | Users, connections, history, schema index |
| Cache | Redis 7 | Query results, sessions, rate limits |
| Target DBs | PostgreSQL, MySQL 8 | Scope-defined connectors |
| Analysis | Pandas, NumPy, SciPy | Profiling, statistics, outlier detection |
| Containers | Docker + Docker Compose | Reproducible dev and demo environments |
| CI/CD | GitHub Actions | Lint, test, build on every push |
| Deployment | Railway or Render (app), Vercel (frontend) | Free/cheap tiers adequate for a capstone |
| Monitoring | Sentry + structured logging (structlog) | Error tracking and traceability |

### Evaluation

| Component | Choice | Purpose |
|---|---|---|
| Benchmarks | Spider, Spider-Realistic, BIRD | Standard text-to-SQL evaluation |
| Metrics | Execution accuracy, exact-set match, valid-SQL rate | Comparable to published results |
| Harness | Custom pytest suite + MLflow | Tracks accuracy across prompt and retrieval variants |

---

## 8. Execution Plan

### Phase 0 — Foundation (Weeks 1–2)

Repository, Docker Compose (Postgres + pgvector + Redis), FastAPI skeleton, React skeleton, CI pipeline, JWT auth. Load the Spider and BIRD datasets locally and stand up the evaluation harness.

*Deliverable:* A running skeleton, health-check endpoint green, benchmark data loaded.

### Phase 1 — Connection & Schema Layer (Weeks 3–4)

Connection manager with encrypted credential storage. Introspection for Postgres and MySQL: tables, columns, types, PK/FK, indexes, sample values. Generate a natural-language description per table, embed it, index into pgvector. Build the FK graph. Connection test and health monitoring.

*Deliverable:* Connect to any Postgres/MySQL instance and produce a complete, searchable schema index.

### Phase 2 — NL→SQL Core (Weeks 5–7)

The critical path. Intent analyzer. Hybrid retrieval (dense + BM25) with FK expansion. Prompt templates per dialect. Structured LLM output via Pydantic. Few-shot example selection by similarity. First end-to-end Spider evaluation run.

*Deliverable:* Working translation, ≥ 65% baseline execution accuracy on Spider dev.

### Phase 3 — Validation, Safety & Execution (Weeks 8–9)

Four-gate validation engine on `sqlglot`. Read-only role provisioning and documentation. Timeouts, row limits, connection pooling. Self-correction loop with error feedback. Redis result caching. Security testing including deliberate prompt-injection attempts.

*Deliverable:* Zero successful write operations across the adversarial test suite; accuracy lifted to ≥ 75% by self-correction.

### Phase 4 — Analytics & Visualization (Weeks 10–11)

Result profiling. Chart-selection rules and Recharts rendering with manual override. Statistical summary and IQR outlier detection. LLM narrative generation. Export to CSV/Excel/JSON/PNG/PDF. Dashboard builder.

*Deliverable:* Every query returns a table, an appropriate chart, and a written summary.

### Phase 5 — Conversation & Learning (Weeks 12–13)

Multi-turn context with coreference resolution. Ambiguity detection and clarifying questions. Query explanation panel. Correction capture feeding the few-shot store. Suggested questions on connect. Business glossary. Semantic caching.

*Deliverable:* Coherent multi-turn sessions; measurable accuracy gain from stored corrections.

### Phase 6 — Hardening & Evaluation (Weeks 14–15)

Full benchmark run on Spider, Spider-Realistic, and BIRD. Ablation study: no-retrieval vs. retrieval; no-correction vs. correction; zero-shot vs. few-shot. Error taxonomy over the failure cases. Load testing. RBAC, audit logging, cost tracking. Accessibility pass. Documentation and deployment.

*Deliverable:* Complete results table with ablations; deployed public demo.

### Phase 7 — Presentation (Week 16)

Final report, slide deck, demo video, live demonstration. Stretch features only if the schedule allows.

### Milestones

| Week | Milestone | Gate |
|---|---|---|
| 2 | Infrastructure complete | CI green, services healthy |
| 4 | Schema indexing working | 200-table DB indexed in < 30 s |
| 7 | First end-to-end query | ≥ 65% Spider dev accuracy |
| 9 | Safe execution verified | Adversarial suite fully blocked |
| 11 | Analytics complete | Charts + insights on every query |
| 13 | Feature complete | All must-have and should-have features shipped |
| 15 | Evaluation complete | Benchmarks + ablations documented |
| 16 | Defense | Report, deck, live demo |

---

## 9. Evaluation Methodology

### 9.1 Metrics

**Execution accuracy** — generated SQL produces the same result set as the gold query. The primary metric; tolerates syntactic variation.

**Exact-set match** — SQL components match the gold query after normalization. Stricter, reported alongside.

**Valid SQL rate** — fraction that parses and executes without error, independent of correctness.

**Correction recovery rate** — fraction of initially failed queries that succeed after self-correction. Directly answers research question 2.

**Schema-linking recall** — fraction of gold-required tables present in the retrieved set. Upper-bounds achievable accuracy; answers research question 1.

**Latency** — p50 / p95 / p99 end-to-end.

**Cost** — tokens and dollars per query.

### 9.2 Datasets

| Dataset | Size | Purpose |
|---|---|---|
| Spider dev | 1,034 queries, 20 DBs | Primary benchmark, comparable to literature |
| Spider-Realistic | 508 queries | Tests without explicit column mentions in the question |
| BIRD dev | 1,534 queries, 95 DBs | Large dirty schemas — closest to production reality |
| Custom set | ~100 queries | Hand-written against a realistic e-commerce schema |

### 9.3 Ablation Study

Each variant runs against the full Spider dev set, isolating one component:

| Variant | Isolates |
|---|---|
| Full system | Baseline |
| − schema retrieval (full schema in prompt) | Value of retrieval |
| − FK expansion | Value of graph-aware expansion |
| − self-correction | Value of the repair loop |
| − few-shot examples | Value of in-context learning |
| Claude vs. GPT | Model sensitivity |

### 9.4 Error Taxonomy

Every failure is categorized: wrong table, wrong column, wrong join, wrong aggregation, wrong filter condition, wrong ordering/limit, ambiguous question, or genuinely unanswerable. The distribution tells us where to invest and forms a substantive section of the final report.

### 9.5 Targets

| Metric | Target | Stretch |
|---|---|---|
| Spider dev execution accuracy | 80% | 85% |
| BIRD dev execution accuracy | 55% | 62% |
| Valid SQL rate | 95% | 98% |
| Schema-linking recall | 95% | 98% |
| Correction recovery rate | 40% | 55% |
| p95 latency | 8 s | 5 s |
| Write operations permitted | 0 | 0 |

---

## 10. Security Model

Defense in depth. Every layer assumes the one above it failed.

| Layer | Control |
|---|---|
| Database | Dedicated role with `SELECT`-only grants; no DDL, no DML. Even a perfect prompt-injection attack cannot write. |
| Query | AST-level rejection of all non-`SELECT` statements, multi-statement queries, comments, and system-catalog access |
| Resource | 30 s statement timeout, 10k row cap, connection pool ceiling, per-user rate limits |
| Credentials | Fernet encryption at rest, never logged, never returned to the client |
| Application | JWT auth, RBAC, per-connection access control |
| Injection | User input never string-concatenated into SQL; parameterized throughout; prompt-injection test suite in CI |
| Audit | Immutable log of user, question, generated SQL, execution status, and timestamp |
| Privacy | Optional PII column masking before results reach the LLM for summarization |

---

## 11. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Accuracy target missed on complex joins | High | High | Schema-linking is the main lever; budget ablation time in Phase 6 to tune retrieval. Fall back to presenting the top-3 candidate queries for user selection. |
| LLM API cost overrun | Medium | Medium | Aggressive semantic caching, token budgets per user, cheaper model for intent classification and summarization |
| LLM latency degrades UX | Medium | Medium | Stream tokens; parallelize retrieval with intent analysis; cache aggressively |
| Very large schemas (1000+ tables) break retrieval | Medium | High | Hierarchical retrieval — schema/domain level first, then table level |
| Prompt injection via database content | Low | High | Read-only role makes this non-fatal; sanitize sample values entering prompts; injection tests in CI |
| API provider outage | Low | High | Dual-provider abstraction with automatic failover |
| Scope creep | High | Medium | Phased plan with explicit non-goals; stretch features gated to Phase 7 |

---

## 12. Expected Outcomes

**Software.** A deployed, documented web platform that connects to a live relational database and answers natural-language questions with validated SQL, results, charts, and written insight.

**Empirical results.** Benchmark numbers on Spider and BIRD with a full ablation study quantifying the contribution of schema-linked retrieval and self-correction — a direct answer to all three research questions.

**Engineering artifact.** An open-source reference implementation of a safety architecture for LLM-generated SQL against production databases, which is the part most published text-to-SQL work omits.

**Documentation.** Final report, architecture documentation, API reference, deployment guide, demo video.

---

## 13. References

1. Yu, T. et al. (2018). *Spider: A Large-Scale Human-Labeled Dataset for Complex and Cross-Domain Semantic Parsing and Text-to-SQL Task.* EMNLP.
2. Li, J. et al. (2023). *Can LLM Already Serve as A Database Interface? A Big Bench for Large-Scale Database Grounded Text-to-SQLs (BIRD).* NeurIPS.
3. Pourreza, M. & Rafiei, D. (2023). *DIN-SQL: Decomposed In-Context Learning of Text-to-SQL with Self-Correction.* NeurIPS.
4. Gao, D. et al. (2023). *Text-to-SQL Empowered by Large Language Models: A Benchmark Evaluation (DAIL-SQL).* VLDB.
5. Wang, B. et al. (2020). *RAT-SQL: Relation-Aware Schema Encoding and Linking for Text-to-SQL Parsers.* ACL.
6. Lewis, P. et al. (2020). *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks.* NeurIPS.
7. Deng, X. et al. (2021). *Structure-Grounded Pretraining for Text-to-SQL (Spider-Realistic).* NAACL.

---

## Appendix A — Repository Structure

```
nlq-analytics-platform/
├── backend/
│   ├── app/
│   │   ├── api/v1/          # route handlers
│   │   ├── core/            # config, security, dependencies
│   │   ├── models/          # SQLAlchemy models
│   │   ├── schemas/         # Pydantic contracts
│   │   ├── services/
│   │   │   ├── connection/  # DB connection management
│   │   │   ├── introspect/  # schema extraction
│   │   │   ├── linking/     # retrieval + FK expansion
│   │   │   ├── generation/  # prompts, LLM clients
│   │   │   ├── validation/  # sqlglot gates
│   │   │   ├── execution/   # sandboxed runner
│   │   │   └── analytics/   # profiling, charts, insights
│   │   └── workers/         # Celery tasks
│   ├── tests/
│   └── evaluation/          # Spider/BIRD harness
├── frontend/
│   └── src/
│       ├── components/      # chat, charts, tables, sql editor
│       ├── hooks/
│       ├── stores/
│       └── api/
├── docker/
├── docs/
└── .github/workflows/
```

## Appendix B — Core API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/v1/auth/login` | Authenticate, return JWT |
| `POST` | `/api/v1/connections` | Register a database connection |
| `POST` | `/api/v1/connections/{id}/test` | Verify connectivity |
| `POST` | `/api/v1/connections/{id}/index` | Trigger schema indexing (async) |
| `GET` | `/api/v1/connections/{id}/schema` | Return the indexed schema graph |
| `POST` | `/api/v1/query` | Submit a natural-language question |
| `WS` | `/api/v1/query/stream` | Streaming query with token-level output |
| `POST` | `/api/v1/query/{id}/execute` | Execute user-edited SQL |
| `POST` | `/api/v1/query/{id}/feedback` | Submit correction or rating |
| `GET` | `/api/v1/history` | Paginated query history |
| `POST` | `/api/v1/dashboards` | Create a dashboard |
| `GET` | `/api/v1/usage` | Token and cost tracking |

## Appendix C — Database Schema (Application)

```sql
users              (id, email, hashed_password, role, created_at)
connections        (id, user_id, name, dialect, host, port, database,
                    encrypted_credentials, status, last_indexed_at)
schema_tables      (id, connection_id, table_name, description,
                    embedding vector(1536), row_estimate)
schema_columns     (id, table_id, column_name, data_type, is_nullable,
                    is_pk, fk_target, sample_values jsonb)
queries            (id, user_id, connection_id, session_id, question,
                    generated_sql, final_sql, status, latency_ms,
                    tokens_used, created_at)
corrections        (id, query_id, corrected_sql, embedding vector(1536))
dashboards         (id, user_id, name, layout jsonb)
audit_log          (id, user_id, action, payload jsonb, created_at)
```
