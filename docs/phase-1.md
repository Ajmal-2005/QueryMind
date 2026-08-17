# Phase 1 - Connection & Schema Layer

Proposal weeks 3-4. Deliverable: *"connect to any Postgres/MySQL instance and
produce a complete, searchable schema index."*

---

## What was built

**Credential storage.** Fernet encryption at rest. Credentials are decrypted
only to open a connection, never logged, and never present in any API
response. The key comes from `CREDENTIAL_ENCRYPTION_KEY`, falling back to a
deterministic derivation from `SECRET_KEY` so development needs no setup.

**Connection manager.** Registers, tests, and opens engines against a target
database. URL assembly percent-encodes credentials, and driver errors are
redacted before they reach a log or an API response, because a failed DSN
contains the password.

**Introspection.** Tables, columns, types, primary keys, foreign keys,
indexes, row estimates, and sample values. Everything structural goes through
SQLAlchemy's `Inspector`, so one code path serves all dialects.

**Table descriptions.** Each table becomes a natural-language paragraph naming
its columns, join paths, and low-cardinality values. This is the text that
gets embedded, so it decides whether retrieval can find anything.

**Embeddings.** A provider interface with two implementations: OpenAI
`text-embedding-3-small` when a key is configured, and a local hashing
vectorizer otherwise.

**Foreign-key graph.** Undirected adjacency with one-hop expansion and
shortest join paths - the structure Phase 2's retrieval expands against.

**API.** `POST /connections`, `GET /connections`, `GET /connections/{id}`,
`POST /{id}/test`, `POST /{id}/index`, `GET /{id}/schema`, `DELETE /{id}`.

**Frontend.** A connections page: add a connection, test it, index it, and
browse the result - tables, columns, keys, join targets, sample values, and
the indexed description itself.

**Demo database.** `scripts/seed_demo_db.py` builds an 8-table e-commerce
schema with 2,000 orders. It deliberately includes a junction table, a
self-referencing hierarchy, a cryptic `cust_ref_log_v2`, and a
low-cardinality `status` column.

---

## Verified

- 145 backend tests pass; ruff and the frontend build are clean.
- Migration applies and reverses.
- Introspection tests run against a real seeded database, not mocks.
- Driven end to end in the browser: register connection → test (6.71 ms,
  SQLite 3.39.4) → index (8 tables, 34 columns, 7 foreign keys, 1 unlinked,
  65 ms) → browse the schema.
- `orders` indexes as: *"Table `orders`. Approximately 2,000 rows. Primary
  key: id. … Joins to `customers` via customer_id = customers.id. Known
  values: status is one of [completed, pending, refunded, cancelled]."*
- Ownership is enforced: another user gets 404, not 403, on someone else's
  connection.
- Credentials never appear in any response body.

## Not verified

- **Postgres and MySQL targets.** All introspection ran against SQLite.
  The code path is shared, but dialect-specific parts - `pg_class.reltuples`,
  `information_schema.TABLES`, the `default_transaction_read_only` connect
  option - have never executed.
- **pgvector.** Embeddings are stored as JSON; the `Vector(1536)` variant has
  never been exercised.
- **OpenAI embeddings.** No API key configured, so only the local embedder
  has run.
- **The 200-table / 30-second milestone gate.** The demo schema has 8 tables
  and indexes in 65 ms. Nothing here establishes behaviour at 200 tables.

---

## Decisions

**SQLite added as a target dialect.** The proposal scopes targets to Postgres
and MySQL. Introspection runs through SQLAlchemy's dialect-agnostic
`Inspector`, so supporting SQLite cost nothing and bought a target database
that needs no server - which is what made Phase 1 demonstrable and testable
without Docker. It is development and demo scope, not a claimed deliverable.

**Descriptions are templates, not LLM-written.** Indexing a 400-table schema
with one LLM call per table is slow and expensive, and a non-deterministic
description makes retrieval evaluation irreproducible. The template expands
abbreviations (`cust_ref_id_v2` → "customer reference identifier v2") so the
embedding sees the words a user would actually type.

**A local hashing embedder as fallback.** It captures lexical overlap only -
it will not match "revenue" to "sales" - so it is honest development
infrastructure, not a substitute for real embeddings. Every benchmark result
must record which provider produced it. The `IndexResult` carries the
embedder name for exactly this reason.

**Trigram weight of 0.5 in the local embedder.** Singular/plural mismatches
between a schema (`orders`) and a question ("order") are constant in this
domain. At the initial 0.3, `customer` and `customers` scored 0.34; the
weight is a deliberate trade of exact-word precision for morphological
recall.

**Embedding column uses `with_variant`.** A real `vector(1536)` on Postgres,
JSON everywhere else. One model definition, no dialect fork in application
code, and local development stays Postgres-free.

**Re-indexing replaces rather than merges.** A dropped column has to
disappear. Reconciling is more code and more ways to be subtly wrong.

**Row estimates come from the statistics catalog.** `reltuples` on Postgres,
`information_schema` on MySQL. An exact `COUNT(*)` against a large production
table during indexing is precisely the query this system must never fire.

**Sample values only for low-cardinality columns.** At most 25 distinct
values, and never for primary or foreign keys. Listing 500 customer emails
would bloat the prompt, teach the model nothing, and put real personal data
into an LLM request.

**404 rather than 403 for another user's connection.** A 403 confirms the id
exists.

---

## Bug found during verification

The connection form sent `port: 0` for file-backed databases, but the API
validates port as 1-65535 when present. Saving a SQLite connection failed
with a 422. Fixed by omitting the port entirely for file databases, and
pinned with two tests: one that a SQLite connection needs no port, and one
that port 0 is rejected.

Worth noting as a process point: the backend tests passed throughout, because
they exercised the contract correctly. Only driving the real UI exposed the
mismatch.

---

## Milestone gate

> Week 4 - Schema indexing working - *200-table DB indexed in < 30 s.*

Indexing works end to end and is fast at demo scale (8 tables, 65 ms), but
the gate as written is **not demonstrated**: there is no 200-table database
here to index, and no Postgres to index it from.

---

## Before Phase 2

1. Install Docker, bring up Compose, and re-run indexing against Postgres.
2. Confirm the pgvector variant creates a real `vector` column.
3. Index a large schema to test the milestone claim honestly.
4. Set `OPENAI_API_KEY` and compare retrieval quality against the local
   embedder - Phase 2's schema-linking recall target of 95% is the number
   that decides whether the local fallback is viable for evaluation.
