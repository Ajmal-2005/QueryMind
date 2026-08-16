# Phase 5 — Conversation & Learning

Weeks 12–13. Features F19–F25.

The theme: everything here is about the system knowing things the schema does
not. A conversation's earlier turns, a definition the organisation holds, a
query a human fixed — none of that is in any `CREATE TABLE`, and all of it
changes the answer.

---

## What was built

| Feature | Where | What it does |
|---|---|---|
| F19 Multi-turn | `generation/intent.py` | Coreference *and* elliptical follow-ups, merged into one instruction |
| F20 Ambiguity clarification | `generation/intent.py` | Targeted questions with clickable rewrites |
| F21 Query explanation | `generation/explain.py` | Clause-by-clause walkthrough from the parsed SQL |
| F22 Learning from corrections | `learning/corrections.py` | Few-shot selection by similarity; corrections outrank successes |
| F23 Suggested questions | `learning/suggestions.py` | Starters generated from the indexed schema |
| F24 Business glossary | `learning/glossary.py` | Term → definition → SQL fragment, injected into the prompt |
| F25 Semantic caching | `cache/semantic.py` | Skips generation when an earlier question meant the same thing |

### F19 — Multi-turn

Phase 2 detected pronouns and glued the two questions together with an em
dash. Three changes:

**Elliptical follow-ups.** "Just the north region" and "only last month" refer
back without containing a single pronoun. They were previously treated as new
questions, which lost the subject entirely.

**One instruction, not two sentences.** `"revenue last quarter — follow-up:
break that down by region"` became `"revenue last quarter, grouped
additionally by: region"`. The instruction words are then stripped from the
tail, so the model is told what to do once rather than twice.

**Context accumulates.** The previous turn is the *resolved* question of that
turn, persisted on `queries.resolved_question`, so a chain keeps what came
before it: "revenue last quarter" → "…by region" → "…just the north" still
carries the time window from two turns back. Time windows and limit hints are
read from the merged text for the same reason.

*This was claimed here before it was true.* The original implementation read
`Query.question` — the text as typed — so the third turn resolved against the
raw second turn and dropped the first. Found by running a three-turn chain
against the live app in Phase 7 and reading the resolved text, not by any
test. The column, and a test that fails without it, arrived then.

### F20 — Targeted clarification

The scope here is narrower than it first looks, deliberately. Phase 2 decided
that a question missing a metric gets *answered* with the assumption stated,
not refused — and that decision holds. F20 is about making the clarifications
that already fire more useful, not about refusing more questions.

So each clarification now names what is missing (`missing: ["metric", "time
period"]`) and carries `clarification_options`: two or three complete
questions the user can send with one click, instead of a paragraph telling
them to be more specific.

### F21 — Query explanation

Reads the **parsed statement**, not the model's prose. The generation already
returns an `explanation`, but that is the model's account of its own work — it
describes what the model *meant*, and where the SQL does something else the
explanation follows the intention.

Both are shown, side by side, labelled. Where they disagree, something is
wrong and the reader can see it. That is the whole point of the feature.

Steps are presented in **evaluation order** — FROM before SELECT — which is
not the order the query is written in and is the order that makes it make
sense.

### F22 — Learning from corrections

The swap Phase 2 left wired: `_few_shot_examples` picked the most recent
successes with a note saying Phase 5 would select by similarity. It now does.

Recency selects whatever happened last, which bears no relationship to the
question being asked now. Three examples about inventory teach nothing about a
revenue question and cost the same tokens as three good ones.

Corrections are ranked **above** plain successes (+0.15 similarity). A query a
human fixed is a place the system got something wrong and was told what right
looks like — the highest-signal data this application ever sees. Which is
exactly why a correction is only stored as `verified` after passing the four
gates *and* executing.

### F23 — Suggested questions

The Ask page shipped with four hardcoded starters. Point the product at an
insurance schema and it offered to rank products that do not exist.

Now generated from the indexed schema: find the largest table, find its
measures and dimensions, phrase the questions those support. Every suggestion
carries the reason it was offered, shown on hover.

### F24 — Business glossary

Matching is deliberately **literal** — a term is used when its words appear in
the question. Embedding similarity was the obvious alternative and the wrong
one: a definition silently applied because it was *nearly* relevant would
change what a query means with no way for the user to see why the number
moved. Applied terms are listed in the provenance panel.

### F25 — Semantic caching

Phase 4's cache keys on SQL, so it only helps *after* the model has been
called. This keys on the question and skips generation entirely.

Three guards, because the failure mode is confidently answering a question
nobody asked:

1. **0.93 cosine** — against 0.15 for picking a few-shot example. A bad
   example wastes tokens; a bad cache hit returns the wrong answer silently.
2. **Polarity and number guards.** "revenue in the north" and "revenue *not*
   in the north" are near-identical in embedding space and are opposites. Any
   disagreement on negation, comparison or superlative words — or on any
   number in the question — blocks the hit whatever the score.
3. **Always visible.** A served hit reports the question it matched, the
   similarity, and the embedder, in the UI.

If the cached SQL fails validation or execution — the schema may have moved —
the loop falls through to real generation rather than giving up.

---

## Verified

**514 backend tests pass** (up from 460), ruff clean, frontend builds and
lints clean.

Exercised against the running app:

- Suggestions come from the demo schema: "What is total amount by month?",
  "Top 5 status by total amount" — no hardcoded starters remain.
- A glossary term (`active customer`) was defined and applied to a live query;
  the provenance panel lists it.
- A correction was saved after passing the gates, then appeared as an example
  on the next similar question, scored 0.89 and labelled `correction`.
- `"break that down by region"` after `"how many active customers per region"`
  resolved to `"…, grouped additionally by: region"` and was flagged
  `is_follow_up`.
- `"show me something"` produced a targeted clarification and three clickable
  rewrites; clicking one asked that question.
- The walkthrough rendered FROM → SELECT → LIMIT with the model's own prose
  beneath it, labelled as the less trustworthy of the two.
- A re-punctuated question hit the semantic cache at 1.0 similarity.
- Sessions do not leak: a follow-up in session B against history in session A
  is not treated as a follow-up.
- `DROP TABLE` is refused as a correction, naming the safety gate.

---

## Not verified

1. **No `ANTHROPIC_API_KEY`.** Still the largest gap. Everything here changes
   the *prompt*, and no prompt has ever reached a real model. Whether richer
   examples and glossary terms actually improve accuracy is unmeasured — this
   phase's contribution to research question 3 is a mechanism, not a result.
2. **Semantic caching is mostly lexical.** The local hashing embedder matches
   on word overlap, so "revenue" will not match "sales" until a real embedding
   provider is configured. The 1.0 similarity observed above is a
   re-punctuation, not a paraphrase. **No cross-vocabulary paraphrase has ever
   been served.**
3. **The +0.15 correction bonus is a judgement, not a measured constant.** So
   is the 0.93 cache threshold and the 0.15 example floor.
4. **Redis, Docker, Postgres, MySQL** — unchanged from earlier phases.
5. Follow-up resolution is rule-based and English-only. A follow-up phrased in
   a way the patterns miss degrades to a new question, which is the safe
   direction but is a real limit.

---

## Decisions

| Decision | Why |
|---|---|
| **F20 does not make more questions ambiguous** | An earlier draft refused "top 5 products" for naming no measure. It broke two existing tests, and rightly — Phase 2 decided such questions get answered with the assumption stated. Refusing more would have been a regression dressed as a feature. |
| **The explanation is parsed, not narrated** | The model's prose describes its intent; the parsed reading describes what will run. Showing both makes a divergence visible instead of hiding it behind one confident paragraph. |
| **Corrections outrank successes** | A query a human fixed carries strictly more information than one that merely ran. |
| **A correction must execute before it is stored** | An unverified correction taught as an example propagates a mistake into every future answer instead of fixing one. |
| **Glossary matching is literal, not semantic** | A definition applied because it was *nearly* relevant would change a query's meaning invisibly. |
| **Glossary expressions are checked for statements** | The fragment is spliced into a prompt and may reach a query. Semicolons, comments and DML are refused. |
| **Semantic cache threshold 0.93, with polarity guards** | Similarity alone cannot distinguish a question from its negation; they are neighbours in embedding space. Cheap word-set comparison catches what cosine cannot. |
| **The semantic cache is per-user** | Reusing a colleague's SQL would leak what they have been asking. |
| **A cached hit that fails falls through to generation** | The schema may have moved since. Better a slow correct answer than a fast stale failure. |
| **Follow-ups skip the semantic cache** | A follow-up depends on conversational context a cached question never had. |

---

## Bugs found during verification

**1. `order` as a noun read as a sort instruction.**
"also show order counts" matched the sort refinement and was rewritten as
"ordered by: show counts" — mangling a request for a column into a request for
an ordering. Every schema this product touches has an `orders` table. The rule
now requires the word to be a verb (`sort by`, or sentence-initial) and runs
last.

**2. Strip order mattered and was wrong.**
"also" is both a leading connective and half of the instruction "also show".
Stripping the connective first left a dangling "show" the instruction pattern
could no longer match. The instruction is now stripped first.

**3. `_embedding_column()` returns a type, not a column.**
`embedding = _embedding_column()` produced an attribute holding a `JSON()`
type object rather than a mapped column, so the table was created without the
column and every insert failed. Caught by the first correction test. Fixed to
match the convention in `schema_index.py`.

*Note for whoever runs this next:* the development `nlq_app.db` had a
`corrections` table created from that broken model. It was patched in place
with `ALTER TABLE ADD COLUMN embedding`. A fresh database gets it right from
`create_all` or the migration.

**4. Suggestions read "total total amount".**
Column names frequently already carry the aggregate word, and the naive
template stuttered. Fixed by checking whether the humanised name already opens
with an aggregate word.

---

## Milestone gate

The proposal does not set a numeric gate for this phase. The functional
target — F19–F25 built — is met, and every feature was exercised in the
running application.

The honest qualification: this phase is entirely about *improving prompt
quality*, and prompt quality cannot be measured without a model. Everything
here is a mechanism whose effect is unmeasured. That measurement is Phase 6's
job and it needs an API key.

---

## Before Phase 6

Phase 6 is where the numbers come from and it is the highest-risk phase.

1. **Set `ANTHROPIC_API_KEY`.** Now blocking three phases' worth of claims.
2. Wire `pipeline.run` into the evaluation harness predictor slot — still the
   placeholder stub.
3. Download Spider, Spider-Realistic, BIRD.
4. The ablation study now has more arms worth running than the proposal listed:
   recency vs similarity example selection, and with vs without the glossary,
   both isolate Phase 5's contribution directly.
