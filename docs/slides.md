# Slide deck — 16 slides, ~15 minutes

One idea per slide. Speaker notes in blockquotes — say them, don't read the
slide aloud.

---

**1 · Title**
AI-Based Natural Language Query Processing and Data Analytics Platform
Capstone · Ajmal Rahman A

---

**2 · The problem**
- A business question takes days: ask an analyst, join a queue, get a number
- BI dashboards answer only what someone anticipated at build time
- The ad-hoc question is the one that matters, and it has no path

---

**3 · What it does**
English question in → validated SQL, a table, a chart, a written summary.

> *One screenshot of the Ask page. Don't explain it yet.*

---

**4 · The claim**
The contribution is **not** the LLM call. It is the four things around it:
1. Schema linking that scales past the context window
2. Validation that catches hallucinated identifiers before execution
3. Self-correction driven by the database's own error messages
4. A safety model that survives being pointed at production

---

**5 · Architecture**
```
question → intent → schema linking → prompt → generation
         → validation → execution → analytics → narrative
```
> One entry point: `pipeline.run()`. The evaluation harness calls that same
> function — a harness that reimplements the pipeline measures the copy.

---

**6 · Schema linking**
- 400 tables do not fit in a prompt
- Dense embeddings catch paraphrase; BM25 catches exact names
- Fused by **rank**, not score — the two scales can't be calibrated reliably
- Then expand one hop along foreign keys

> The junction table a join needs is exactly the table no retriever ranks
> highly. That's what expansion is for.

---

**7 · Safety — three independent layers**
1. The prompt forbids writes
2. Four gates: syntax → **safety** → schema → cost
3. The connection is opened read-only

> Only the third is enforced outside my code. Safety runs *before* schema
> deliberately: otherwise `DROP TABLE misspelled` looks like a typo worth
> repairing.

---

**8 · Result: 43 / 43 adversarial cases blocked**
All hard rejections. A safety failure never retries — regenerating a refused
write turns one blocked request into three requests for the same thing.

---

**9 · Self-correction**
generate → validate → execute, feeding database errors back, up to 3 attempts.

> Database errors are unusually good repair signals: "no such column:
> cust_name", not "query failed". The schema gate deliberately produces
> messages in the same shape.

---

**10 · Analytics**
Profile → chart → outliers → trend → narrative.
- Chart chosen by rule from result shape, and the rule is shown
- Two outlier methods, because they disagree usefully
- The model is given **computed statistics**, never raw rows to add up

---

**11 · Privacy**
PII masked before any row leaves the deployment — by column name *and* value
pattern.

> Found in testing: the sample rows were masked but the profile's "most common
> values" were not. Masking has to apply at the boundary, not to one object
> that crosses it.

---

**12 · Measured result — schema linking**

| arm | recall | all found |
|---|---|---|
| hybrid + FK | 100% | 100% |
| no expansion | 97.5% | 90% |
| k=1 | 87.5% | 80% |
| **k=10 (control)** | **100%** | **100%** |

FK expansion helps consistently.

---

**13 · …and why that table proves nothing**
The demo schema has 8 tables. The retriever returns **98% of them**.
The `k=10` control retrieves everything and also scores 100%.

> The harness prints "NOT DISCRIMINATIVE" itself. I built that guard so a
> table of 100%s couldn't be reported as success. Spider is what makes this
> question answerable.

---

**14 · What is not measured**
- **No accuracy figure exists.** No API key → the pipeline uses a stub that
  never reads the question
- Both Anthropic clients written, never called
- Postgres, Redis, Docker: written, never run
- `temperature=0` is impossible on current models — **the proposal is wrong**

> I have not estimated a number in place of measuring one.

---

**15 · Measured: concurrency**
8.0 → 8.6 → 8.5 req/s at 1 → 5 → 20 users. Latency grows linearly.
Flat throughput = complete serialisation: SQLite's single writer.

> Also: I misdiagnosed a 2 s latency as embedding cost. Every endpoint took
> exactly 2028 ms — a constant across unrelated endpoints is the measurement,
> not the system. IPv6 fallback. 4 ms on `127.0.0.1`.

---

**16 · Where it stands**
- All 25 functional requirements implemented · 547 tests pass
- Safety model verified and holding
- Research questions **open** — one API key and two downloads from answerable
- Complete as software, incomplete as research, and honest about which

---

## If you have only 5 minutes

Slides 2 → 4 → 7 → 8 → 13 → 16.
The safety result and the non-discriminative finding are the two strongest
things you have.
