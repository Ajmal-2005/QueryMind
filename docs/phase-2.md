# Phase 2 — NL→SQL Core

Proposal weeks 5–7. Deliverable: *"working translation, ≥ 65% baseline
execution accuracy on Spider dev."*

---

## What was built

**Intent analyzer.** Classifies a question as aggregation, comparison, trend,
ranking, filter, or ambiguous. Resolves follow-ups ("break that down by
region") against earlier turns in the same session, spells out relative dates
("last quarter" → the previous complete calendar quarter), extracts explicit
row limits, and returns a clarifying question instead of guessing when a
question is genuinely contentless.

**Hybrid retrieval.** Dense cosine over the stored table embeddings plus BM25
over the table descriptions, fused with reciprocal rank fusion, then expanded
one hop along the foreign-key graph.

**Prompt construction.** The retrieved subgraph renders as `CREATE TABLE`
DDL — including primary keys, foreign-key references, row estimates, and
low-cardinality sample values — with per-dialect rules for Postgres, MySQL,
and SQLite, explicit join paths, resolved time windows, and few-shot
examples. The same builder produces the repair prompt Phase 3's
self-correction loop will use.

**LLM layer.** A provider interface with an Anthropic implementation, a
deterministic offline stub, and a scripted test double.

**Pipeline and API.** `POST /api/v1/query` runs intent → retrieval →
generation, persists every attempt, and returns the SQL, confidence,
explanation, assumptions, the retrieved table set, and per-stage timings.
`GET /api/v1/query/history` lists a user's past questions.

**Ask workspace.** A chat surface with starter prompts, SQL syntax
highlighting, a copy button, an assumptions callout, and a "How this was
built" panel showing the retrieved tables, which of them arrived via
foreign-key expansion, the model and embedder used, token count, and stage
timings.

---

## Verified

- 230 backend tests pass; ruff and the frontend build are clean.
- Driven end to end in the browser: a question returns SQL in ~170 ms with
  the full provenance panel; a vague question returns a clarifying question
  and never reaches the model; a follow-up resolves against the prior turn
  and retrieves `customers`, the table holding `region`.
- Schema-linking recall is 100% on the two hand-checked gold sets in
  `test_retriever.py` (revenue-by-category and customer-spend).
- Foreign-key expansion pulls in `product_suppliers` for a
  products-and-suppliers question, which is the case retrieval alone misses.
- Zero console errors; every API call returns 200.

## Not verified

- **Any accuracy figure.** No `ANTHROPIC_API_KEY` is configured, so every run
  used the stub, which returns `SELECT * FROM <first table> LIMIT 10` and
  does not read the question. **The Phase 2 deliverable — ≥ 65% on Spider
  dev — is not met and cannot be measured until a key is available.**
- **The Anthropic client has never executed.** It is written against the
  current API but has not made a live call.
- **Spider and BIRD** are still not downloaded, so the harness has no
  benchmark to run beyond the committed 10-question custom set.
- **Retrieval at scale.** The demo schema has 8 tables; the default `top_k`
  of 6 excludes almost nothing there. The exclusion behaviour is tested with
  a tighter budget, but nothing here establishes recall on a 400-table
  schema.

---

## Decisions

**The proposal's "temperature 0 for determinism" is not achievable.**
Sampling parameters — `temperature`, `top_p`, `top_k` — are rejected with a
400 on Claude Sonnet 5 and every current frontier model. Determinism now has
to come from the prompt and from `effort`, not from a sampling knob. This is
worth stating plainly in the final report, since the proposal claims it as a
design property.

**Structured output rather than prefill.** The proposal's design implies
coaxing JSON out of the model; assistant-turn prefill is also rejected on
current models. Instead the request carries a JSON schema via
`output_config.format`, so the response is guaranteed to parse and there is
no regex extraction step to get wrong.

**Intent analysis is rule-based.** The proposal budgets 300 ms for this
stage, which an LLM round trip cannot meet. The classification only steers
the prompt and the later chart choice, so a wrong label degrades quality
rather than breaking correctness — a poor trade for a second API call per
question.

**Reciprocal rank fusion rather than score normalisation.** Cosine
similarity and BM25 live on different scales, and calibrating them against
each other is fragile and dataset-specific. RRF reads only rank position, so
the calibration problem does not arise.

**BM25 implemented directly.** The corpus is a few hundred short documents
and the scoring is twenty lines; a dependency would cost more than it saved.

**A stub provider rather than a hard failure without a key.** The pipeline,
the API, and the UI are all exercisable offline. The stub is loud about what
it is — confidence 0, an explicit assumption saying no model ran, and the
model name `stub` in the provenance panel — precisely so a stub run can
never be mistaken for a measured one.

**An ambiguous question never reaches the model.** Guessing costs tokens and
produces a confidently wrong answer; the clarifying question is both cheaper
and more honest. Tested by asserting the model client is not called at all.

**Few-shot examples come from past successful queries on the connection.**
Phase 5 selects these by embedding similarity; the wiring is in place now so
that change is a swap of one function.

---

## Bug found during verification

The vagueness heuristic rejected "Top 5 products" as ambiguous — it is three
words, and the word-count floor fired before the intent match was consulted.
Fixed so the length check applies only when no intent pattern matched at all,
which is where genuinely contentless input ("data?") lands.

---

## Milestone gate

> Week 7 — First end-to-end query — *≥ 65% Spider dev accuracy.*

End-to-end translation works and the whole pipeline is exercised. The
accuracy half of the gate is **not met**: with no API key there is no
measurable accuracy, and Spider is not downloaded.

---

## Before Phase 3

1. Set `ANTHROPIC_API_KEY` and confirm the Anthropic client works against the
   live API.
2. Download Spider into `backend/evaluation/data/spider/` and wire the
   pipeline into the harness's predictor slot.
3. Run the first real Spider evaluation and record the baseline honestly,
   whatever it is.
4. Compare the local hashing embedder against `text-embedding-3-small` on
   schema-linking recall — that number decides whether the local fallback is
   viable for the evaluation runs.
