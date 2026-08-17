# AI-Based Natural Language Query Processing and Data Analytics Platform

Final report. Companion to [`proposal.md`](../proposal.md); per-phase detail
in [`docs/phase-0.md`](phase-0.md) … [`docs/phase-6.md`](phase-6.md).

---

## 1. What was built

A web platform where a user asks a question in English against a live
relational database and receives validated SQL, a result table, a chart, and a
written summary.

The contribution is not the language-model call. It is the pipeline around it:
schema linking that scales past the context window, a validation layer that
catches hallucinated identifiers before execution, a self-correction loop
driven by the database's own error messages, and a safety model that makes the
system safe to point at a production replica.

**Scale:** 9 commits across 7 phases. ~12,300 lines of backend Python, ~5,700
lines of backend tests, ~5,200 lines of TypeScript. 547 tests pass; ruff and
oxlint clean.

**Every feature F1-F25 in the proposal is implemented**, plus F29 (cost
tracking). What is *not* done is the measurement - see §5.

---

## 2. Architecture

```
question
  → intent analysis        rule-based: type, follow-up, dates, limits
  → schema linking         dense + BM25 → RRF → 1-hop FK expansion
  → prompt construction    retrieved subgraph as DDL + glossary + examples
  → generation             Anthropic, structured output
  → validation             syntax → SAFETY → schema → cost
  → execution              read-only connection, statement timeout, row cap
  → analytics              profile → chart → outliers → trend
  → narrative              exact statistics + PII-masked sample
```

`pipeline.run()` is the single entry point. The evaluation harness calls that
same function - a harness that reimplements the pipeline measures the
reimplementation.

### Design decisions that shaped the system

**Schema linking is hybrid, fused by rank not score.** Dense embeddings catch
paraphrase; BM25 catches exact identifier matches. Their scores live on
different scales and calibrating them is fragile, so reciprocal rank fusion
reads only rank position. Retrieval then expands one hop along foreign keys,
because ranking tables independently routinely returns two tables with no edge
between them - the junction table needed for the join is exactly the table no
retriever ranks highly.

**Safety runs before schema validation.** Reversed, `DROP TABLE misspelled`
returns as a retryable schema error and re-enters the correction loop. A
safety failure never retries: regenerating a refused write turns one blocked
request into three requests for the same forbidden thing.

**Three independent defences against writes.** The prompt forbids them; the
gates reject them; and the connection is opened read-only (`mode=ro` on
SQLite, read-only sessions on Postgres/MySQL) so the driver refuses regardless
of what the first two did. Only the third is enforced outside this codebase.

**Analytics reads a profile, not the rows.** Type inference happens once -
which matters because SQLite has no date type and returns `DATE` columns as
strings, the case naive inference gets wrong.

**Statistics are computed locally and given to the model.** A model handed
10,000 raw rows must add them up itself and will sometimes get it wrong while
sounding equally confident. Every number in a generated summary traces to
arithmetic this process performed.

**Corrections outrank successes as examples.** A query a human fixed is a
place the system was wrong and was told what right looks like. It is stored
only after passing the same gates and executing - an unverified correction
taught as an example propagates a mistake instead of fixing one.

---

## 3. Security and privacy

| Control | Mechanism |
|---|---|
| Credentials | Fernet-encrypted at rest, never logged, never returned by the API |
| Write prevention | Prompt + four gates + read-only connection |
| Injection | sqlglot parse, allow-list of statement types, no string concatenation |
| Result size | Row cap read one past the limit so truncation is reported |
| Ownership | Connections, dashboards, corrections 404 to non-owners |
| RBAC | `require_roles` gates the audit trail |
| Audit | Append-only log of queries, exports, corrections, deletions |
| PII | Column-name *and* value-pattern masking before any row leaves the box |

**Adversarial testing: 43 of 43 cases blocked**, all as hard rejections, with
independent confirmation that the connection itself refuses writes.

PII masking replaces values with type tokens (`<email>`) rather than partial
masks - a partial mask leaks the domain, the last four digits, the name
length, and the narrator never needs the value, only the shape.

---

## 4. Results

### 4.1 Schema linking (measured)

The one part of the system measurable without an API key, and the part
research question 1 asks about. 10 questions, 8-table schema, local embedder:

| arm | recall | all tables found | schema retrieved |
|---|---|---|---|
| **hybrid + FK expansion** | 100.0% | 100.0% | 98% |
| hybrid, no expansion | 97.5% | 90.0% | 75% |
| dense only + FK | 100.0% | 100.0% | 95% |
| sparse only + FK | 100.0% | 100.0% | 100% |
| sparse, no expansion | 94.2% | 80.0% | 75% |
| hybrid + FK, k=1 | 87.5% | 80.0% | 35% |
| hybrid + FK, k=10 *(control)* | 100.0% | 100.0% | 100% |

**Finding 1.** Foreign-key expansion helps consistently - +2.5 points of
recall and +10 points of all-tables-found in every mode, +5.8 / +20 for BM25
alone. Directional support for research question 1.

**Finding 2, and the more important one: this result does not discriminate,
and the harness says so itself.** The default configuration retrieves 98% of
an 8-table schema. Nearly every arm finds nearly every gold table because
nearly every table is being sent. Hybrid fusion shows no advantage over either
retriever alone, and the `k=10` control retrieves the entire schema and also
scores 100% - which is precisely why that control exists. A recall win that a
larger `k` also buys is not a win for the method.

Answering research question 1 properly requires Spider's larger schemas. The
machinery is ready; the data is not downloaded.

### 4.2 Concurrency (measured)

| concurrent users | throughput | p50 latency |
|---|---|---|
| 1 | 8.0 req/s | 123 ms |
| 5 | 8.6 req/s | 573 ms |
| 20 | 8.5 req/s | 1861 ms |

200/200 requests succeeded at 20-way concurrency; nothing deadlocked. But
throughput is flat while latency grows linearly - the signature of complete
serialisation. The cause is structural: SQLite permits one writer, every
answered question writes two rows, and uvicorn ran a single worker. Postgres
is the documented deployment target and would remove the write serialisation.
It has never been run.

### 4.3 Accuracy - not measured

**No accuracy figure exists for this system.** There is no `ANTHROPIC_API_KEY`
in the development environment, so the pipeline falls back to a stub that
returns `SELECT * FROM <first table> LIMIT 10` without reading the question.

Consequently:
- Phase 2's ≥65% and Phase 3's ≥75% execution-accuracy gates are **unmet and
  unmeasurable**.
- Research question 2 (does error-driven self-correction recover failures?) has
  a complete implementation and **no measurement**.
- Research question 3 (does learning from corrections help?) likewise.

No estimate is offered in place of a measurement. The harness is finished and
wired to the production pipeline; one environment variable produces the first
real number.

---

## 5. Honest limitations

Stated plainly, because they are the difference between a report and a sales
pitch.

1. **Nothing has been run against a real language model.** Two Anthropic
   clients exist - SQL generation and narrative - and neither has ever been
   called. Every prompt-quality improvement in Phase 5 is a mechanism with an
   unmeasured effect.

2. **`temperature=0` is not achievable.** The proposal claims it as a design
   property. Sampling parameters return HTTP 400 on Claude Sonnet 5 and every
   current frontier model. Determinism comes from the prompt and the effort
   setting instead. **The proposal is wrong on this point and the report
   should say so.**

3. **Pandas/NumPy/SciPy were not used**, despite the proposal's stack. Result
   sets are capped at 10,000 rows and the arithmetic is ~100 lines of the
   standard library's `statistics`; type inference had to be hand-written
   regardless, because Pandas fights SQLite's dynamic typing.

4. **The local embedder is lexical.** Without an `OPENAI_API_KEY` it matches
   word overlap, so it will not connect "revenue" to "sales". Semantic caching
   therefore serves re-punctuations, never true paraphrases. Every result
   records which embedder produced it.

5. **Docker, Postgres, MySQL, Redis, pgvector: written, never executed.** The
   read-only session guards and statement timeouts for Postgres and MySQL have
   never run against those databases.

6. **The ablation cannot discriminate** on the only available schema.

7. **No accessibility audit was performed.** Contrast and keyboard navigation
   were considered while building; nothing was tested with a screen reader or
   an automated checker.

8. **Thresholds are judgements, not measured constants** - the 0.93 semantic
   cache threshold, the +0.15 correction bonus, the 1.5 IQR multiplier.

---

## 6. Bugs found by verification

Each phase's verification found defects that reading the code had not. The
most instructive:

**PII masking leaked through the profile.** Sample rows sent to the model were
masked; the profile's "most common values" - real customer names - were not.
The general lesson: *masking must apply at the boundary, not to one object
that happens to cross it.*

**Every `GROUP BY` key was classified as free text.** A distinct/total ratio
guard intended to exclude identifier columns rejected exactly the column type
this product charts most often, since a `GROUP BY` produces one row per key by
construction.

**A 2-second latency that was not there.** Load testing showed ~2.1 s per
request against a pipeline reporting 80 ms. I attributed it to embedding cost
and wrote a fix. It was wrong: *every* endpoint including `/health` took
exactly ~2028 ms, and a constant across unrelated endpoints is a property of
the measurement. `localhost` was resolving to IPv6 against an IPv4-only
server. 4 ms against `127.0.0.1`. The false claim had already been written
into a source comment before it was caught.

**`order` as a noun read as a sort instruction.** "Also show order counts"
became "ordered by: show counts" - in a product where every schema has an
`orders` table.

---

## 7. Conclusion

The system is complete as software and incomplete as research. All 25
functional requirements are implemented, the safety model is verified against
43 adversarial cases and holds, and the analytics and conversation layers work
end to end in the running application.

The research questions remain open. One measurement was possible without a
model and was taken; it points the right way and does not discriminate, and
the harness reports that itself rather than allowing a table of 100%s to read
as success.

What separates this from a finished project is one API key and two dataset
downloads - not further engineering. What separates it from an overclaimed one
is that every unmeasured thing above is named.

---

## 8. Future work

1. Set `ANTHROPIC_API_KEY`; run the harness. First accuracy figure, correction
   recovery rate, and error taxonomy in a single command.
2. Download Spider and re-run the ablation on schemas large enough to
   discriminate.
3. Docker → Postgres and Redis: exercises pgvector, the session guards, the
   shared cache, and should lift the ~8.5 req/s ceiling.
4. OpenAI as a second provider, enabling the model A/B and the embedder
   comparison the proposal specifies.
5. Move indexing to Celery - synchronous introspection will not survive a
   400-table schema.
