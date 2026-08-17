# AI-Based Natural Language Query Processing and Data Analytics Platform

Complete project reference. Written to be turned into a presentation - each
numbered section is roughly one slide, with the speaker's line in
blockquotes and the numbers already checked.

**Author:** Ajmal Rahman A · **Capstone** · Natural Language Query Processing

---

## 1. One-line summary

A web platform where a user asks a question in plain English against a live
relational database and gets back validated SQL, a result table, a chart, and
a written summary.

---

## 2. The problem

- A business question takes days: ask an analyst, join a queue, get a number.
- BI dashboards only answer what someone anticipated when they were built.
- The ad-hoc question is the one that matters, and it has no path.

> Existing tools are rigid. Every new question needs a new dashboard, which
> needs an analyst - straight back to the bottleneck.

---

## 3. The claim (the thesis of the project)

**The contribution is not the LLM call.** Anyone can send a question to a
model. The contribution is the four things around it:

1. **Schema linking** that scales past the context window
2. **Validation** that catches hallucinated identifiers before execution
3. **Self-correction** driven by the database's own error messages
4. **A safety model** that survives being pointed at a production replica

> If the demo is "I sent a question to GPT", there is no project. The project
> is everything that makes that safe, scalable and checkable.

---

## 4. Research questions

| # | Question | Status |
|---|---|---|
| RQ1 | Does retrieval-based schema linking scale to large schemas? | **Partially measured** - directional, not conclusive |
| RQ2 | Does error-driven self-correction recover a meaningful share of failures? | Implemented, **not measured** |
| RQ3 | Does learning from user corrections improve accuracy? | Implemented, **not measured** |

---

## 5. Architecture (the pipeline)

```
question
  -> intent analysis      rule-based: type, follow-up, dates, limits
  -> schema linking       dense + BM25 -> RRF -> 1-hop FK expansion
  -> prompt construction  retrieved subgraph as DDL + glossary + examples
  -> generation           Gemini / OpenAI / Anthropic, structured output
  -> validation           syntax -> SAFETY -> schema -> cost
  -> execution            read-only connection, timeout, row cap
  -> analytics            profile -> chart -> outliers -> trend
  -> narrative            exact statistics + PII-masked sample
```

**`pipeline.run()` is the single entry point.** The evaluation harness calls
that same function.

> A harness that reimplements the pipeline measures the reimplementation.

---

## 6. Technology stack

| Layer | Choice |
|---|---|
| Backend | Python 3.10, FastAPI, SQLAlchemy 2.0, Pydantic |
| Frontend | React 19, TypeScript, Vite, Tailwind, Recharts |
| SQL parsing | sqlglot (validation, explanation, gold-table extraction) |
| LLM | Google Gemini (primary in practice), OpenAI, Anthropic |
| Databases | SQLite, PostgreSQL, MySQL (dialect-agnostic introspection) |
| Auth | JWT, bcrypt, Fernet-encrypted credentials |
| Cache | Redis, with an in-process fallback |
| Testing | pytest (556 tests), ruff, oxlint |

---

## 7. Schema linking - the scaling problem

**Problem:** 400 tables do not fit in a prompt.

**Solution - hybrid retrieval:**
- **Dense embeddings** catch paraphrase ("revenue" -> `orders.total_amount`)
- **BM25** catches exact identifier matches
- **Reciprocal Rank Fusion** combines them by *rank*, not score
- **One-hop foreign-key expansion** adds joinable neighbours

> Cosine and BM25 scores live on different scales and calibrating them is
> fragile. RRF reads only rank position, so it never has to.

**Why FK expansion matters:** ranking tables independently routinely returns
two tables with no edge between them. The junction table needed for the join
is exactly the table no retriever ranks highly.

---

## 8. Safety - three independent layers

1. **The prompt** forbids writes
2. **Four validation gates:** syntax -> **safety** -> schema -> cost
3. **The connection is opened read-only** (`mode=ro` on SQLite; read-only
   sessions on Postgres/MySQL)

> Only the third is enforced outside my own code. That is the point of it.

**Two deliberate ordering decisions:**

- **Safety runs before schema validation.** Reversed, `DROP TABLE misspelled`
  comes back as a retryable schema error and re-enters the correction loop.
- **Safety failures never retry.** Regenerating a refused write turns one
  blocked request into three requests for the same forbidden thing.

### Result: 43 of 43 adversarial cases blocked

All hard rejections, plus independent confirmation that the connection itself
refuses writes.

---

## 9. Self-correction loop

```
generate -> validate -> execute
     ^                      |
     +---- error message ---+   (up to 3 attempts)
```

> Database errors are unusually good repair signals because they are specific:
> "no such column: cust_name", not "query failed". The schema gate
> deliberately produces messages in the same shape, with a "did you mean"
> hint, so a validation failure repairs as readily as an execution one.

---

## 10. Analytics layer

`profile -> chart -> outliers -> trend -> narrative`

- **Chart selection is rule-based** from result shape, and the rule is shown
  to the user: date column -> line; one category -> bar; two numerics ->
  scatter; single value -> KPI; otherwise table.
- **Two outlier methods** (IQR and z-score) because they disagree usefully -
  revenue is right-skewed, and one large value inflates the standard deviation
  enough to hide its own z-score. Quartiles cannot be moved by it.
- **The model receives computed statistics**, never raw rows to add up.

> A model handed 10,000 rows has to add them up itself, and will sometimes get
> it wrong while sounding equally confident. Every number in a summary traces
> to arithmetic this process performed.

---

## 11. Privacy - PII masking

Masking runs before any row leaves the deployment, using **two independent
detectors**:

- **Column names** - `email`, `full_name`, `dob` (catches data with no
  distinctive format)
- **Value patterns** - email, Luhn-checked card, national ID, IBAN, IP, phone

Values are replaced with **type tokens** (`<email>`), not partial masks.

> A partial mask leaks the domain, the last four digits, the name length. The
> narrator never needs the value, only the shape.

---

## 12. Conversation and learning (F19-F25)

| Feature | What it does |
|---|---|
| **Multi-turn** | "break that down by region" -> "just the north" - chains accumulate context |
| **Clarification** | Names what is missing and offers clickable rewrites |
| **Explanation** | Clause-by-clause walkthrough read from the *parsed SQL* |
| **Corrections** | User-fixed SQL becomes a ranked few-shot example |
| **Suggestions** | Starter questions generated from the indexed schema |
| **Glossary** | "active customer" -> an agreed SQL definition |
| **Semantic cache** | Skips generation for a question already answered |

**The explanation feature is worth a slide of its own.** It reads the parsed
statement, not the model's prose, and both are shown side by side.

> The model's paragraph describes what it *meant*. The steps describe what
> will *run*. Where they disagree, something is wrong, and you can see it.

---

## 13. Measured result: schema linking (RQ1)

10 questions, 8-table schema, local embedder:

| Arm | Recall | All tables found | % schema retrieved |
|---|---|---|---|
| **hybrid + FK expansion** | 100.0% | 100.0% | 98% |
| hybrid, no expansion | 97.5% | 90.0% | 75% |
| dense only + FK | 100.0% | 100.0% | 95% |
| sparse only + FK | 100.0% | 100.0% | 100% |
| sparse, no expansion | 94.2% | 80.0% | 75% |
| hybrid + FK, k=1 | 87.5% | 80.0% | 35% |
| **hybrid + FK, k=10 (control)** | 100.0% | 100.0% | 100% |

**Finding 1:** FK expansion helps consistently - +2.5 recall, +10 on
all-tables-found, in every mode.

---

## 14. …and why that table proves nothing

The demo schema has 8 tables. The default configuration **retrieves 98% of
them**. Nearly every arm finds nearly every gold table because nearly every
table is being sent.

The `k=10` control retrieves the entire schema and also scores 100%.

**The harness prints `NOT DISCRIMINATIVE` itself.**

> I built that guard so a table of 100%s could not be reported as success. A
> recall win that a larger `k` also buys is not a win for the method. Spider
> is what makes this question answerable.

*This is the strongest slide in the deck. Negative results reported honestly
are worth more than inflated positive ones.*

---

## 15. Measured result: concurrency

| Concurrent users | Throughput | p50 latency |
|---|---|---|
| 1 | 8.0 req/s | 123 ms |
| 5 | 8.6 req/s | 573 ms |
| 20 | 8.5 req/s | 1861 ms |

200/200 requests succeeded at 20-way concurrency; nothing deadlocked.

**But throughput is flat while latency grows linearly** - the signature of
complete serialisation. SQLite permits one writer, every answered question
writes two rows, and uvicorn ran a single worker. Postgres is the documented
deployment target and would remove the write serialisation.

---

## 16. What is NOT measured (say this out loud)

- **No execution-accuracy figure exists.** The accuracy gates in the proposal
  are unmet **and unmeasurable** without a benchmark run.
- Anthropic and OpenAI clients: written, **never successfully called**
  (the OpenAI key returns `429 insufficient_quota` on every request).
- Postgres, MySQL, Redis, Docker, pgvector: written, **never run**.
- The ablation **cannot discriminate** on the only schema available.
- No accessibility audit was performed.

> I have not estimated a number in place of measuring one.

---

## 17. Two corrections to the original proposal

1. **`temperature=0` is not achievable.** Sampling parameters return HTTP 400
   on current frontier models. Determinism comes from the prompt and the
   effort setting instead. *(It is available on the OpenAI path, which is
   itself an interesting asymmetry.)*
2. **Pandas/NumPy/SciPy were not used.** Result sets are capped at 10,000
   rows; the arithmetic is ~100 lines of the standard library's `statistics`,
   and type inference had to be hand-written anyway because Pandas fights
   SQLite's dynamic typing.

---

## 18. Bugs found by verification (good viva material)

**PII masking leaked through the profile.** The sample rows sent to the model
were masked; the profile's "most common values" - real customer names - were
not.

> The lesson generalises: masking must apply at the boundary, not to one
> object that happens to cross it.

**Every `GROUP BY` key was classified as free text.** A distinct/total ratio
guard, meant to exclude identifier columns, rejected exactly the column type
this product charts most often - because a `GROUP BY` produces one row per key
by construction.

**A 2-second latency that was not there.** Load testing showed ~2.1 s per
request against a pipeline reporting 80 ms. I attributed it to embedding cost
and wrote a fix. It was wrong: *every* endpoint including `/health` took
exactly ~2028 ms, and a constant across unrelated endpoints is a property of
the measurement, not the system. `localhost` was resolving to IPv6 against an
IPv4-only server. 4 ms against `127.0.0.1`.

**`order` as a noun read as a sort instruction.** "Also show order counts"
became "ordered by: show counts" - in a product where every schema has an
`orders` table.

**A documented feature that did not work.** The Phase 5 write-up claimed
follow-up chains accumulate context. They did not: session history stored the
question *as typed*, so turn three resolved against turn two's ellipsis and
dropped turn one. Found by reading resolved text off the live app, not by any
test. Fixed, with regression tests.

---

## 19. Engineering scale

| Metric | Value |
|---|---|
| Backend Python | ~12,800 lines |
| Backend tests | ~5,800 lines, **556 tests passing** |
| Frontend TypeScript | ~5,400 lines |
| Commits | 21, across 7 phases |
| Features delivered | **All 25 (F1-F25)**, plus F29 cost tracking |
| Lint | ruff and oxlint clean |

---

## 20. Development phases

| Phase | Delivered |
|---|---|
| 0 | Foundation - FastAPI + React, auth, health, CI, eval harness |
| 1 | Connection manager, schema introspection, searchable index |
| 2 | NL->SQL core - intent, hybrid retrieval, generation |
| 3 | Validation gates, sandboxed execution, self-correction |
| 4 | Analytics, charts, dashboards, exports, result cache |
| 5 | Conversation, corrections, glossary, semantic cache |
| 6 | Evaluation harness, ablation study, error taxonomy, RBAC |
| 7 | Report, slide deck, demo runbook |

---

## 21. Live demo script

**Best opener - "Which customers have never placed an order?"**

```sql
SELECT c.id, c.full_name, c.email FROM customers AS c
LEFT JOIN orders AS o ON c.id = o.customer_id WHERE o.id IS NULL
```

> That is an anti-join. Nobody phrases the question that way, and it is the
> shape people assume these systems get wrong.

**Then:**
1. **"Which suppliers have the longest average lead time?"** - the junction
   table arrives via FK expansion
2. **"Walk me through this query"** - the explanation panel
3. **"How many active customers per region?"** - the glossary in action
4. **Safety** - run `pytest tests/test_adversarial.py` (do *not* ask the model
   to delete anything; it correctly refuses to generate a write, so the gate
   never fires)
5. **The ablation** - `python -m evaluation.runner --ablation`, then point at
   `NOT DISCRIMINATIVE`

---

## 22. Questions you will be asked

**"What accuracy does it achieve?"**
> None measured. The harness is finished and wired to the production pipeline;
> one benchmark download produces the first number. I have not estimated one.

**"Why not put the whole schema in the prompt?"**
> Works at 8 tables, fails at 400 - context limits and cost. That is exactly
> research question 1.

**"How do you know it won't drop a table?"**
> Three independent layers, and the third is enforced by the database rather
> than by my code.

**"What is the weakest part?"**
> That nothing has been measured against a benchmark. Second: the local
> embedder matches word overlap, so it will not connect "revenue" to "sales".
> Both are stated in every phase document.

---

## 23. Future work

1. Download Spider (200 databases, 1,034 questions with gold SQL) and re-run
   the ablation on schemas large enough to discriminate.
2. Docker -> Postgres and Redis: exercises pgvector, the session guards, the
   shared cache, and should lift the ~8.5 req/s ceiling.
3. A funded LLM key for the full benchmark, the correction recovery rate, and
   the model A/B the proposal specifies.
4. Move indexing to Celery - synchronous introspection will not survive a
   400-table schema.

---

## 24. Closing statement

> All 25 functional requirements are implemented. The safety model is verified
> against 43 adversarial cases and holds. The analytics and conversation
> layers work end to end.
>
> The research questions remain open. One measurement was possible without a
> benchmark and was taken - it points the right way and does not discriminate,
> and the harness reports that itself rather than letting a table of 100%s
> read as success.
>
> The project is complete as software and incomplete as research, and it is
> explicit about which is which.

---

## Appendix: suggested slide order (16 slides, ~15 min)

1. Title · 2. Problem · 3. What it does *(screenshot)* · 4. The claim
5. Architecture · 6. Schema linking · 7. Safety layers · 8. **43/43 blocked**
9. Self-correction · 10. Analytics · 11. Privacy · 12. **Ablation table**
13. **Why it proves nothing** · 14. Not measured · 15. Concurrency
16. Where it stands

**If you only have 5 minutes:** 2 -> 4 -> 7 -> 8 -> 13 -> 16.
The safety result and the non-discriminative finding are the two strongest
things in the project.
