# Live demo runbook

Everything below has been run and works. Timings assume no API key - if one
is set, add a few seconds per question and the answers become real.

---

## Before you start (5 minutes)

```bash
cd backend && .venv/Scripts/python -m uvicorn app.main:app --port 8000
```

```bash
cd frontend && npm run dev
```

Open **http://localhost:5173**. Sign in as `demo4@example.com` /
`correct-horse-battery`, or register - the first account on a fresh database
becomes admin.

Check before presenting:
- Connections page shows **Demo e-commerce** with status `indexed`.
- Ask page shows starter questions naming real tables (orders, products).
- Glossary page shows `active customer` and one saved correction.

If the connection is missing: **Add connection → SQLite (file)** → paste the
path printed by `python -m scripts.seed_demo_db` → **Test** → **Index schema**.

---

## The 10-minute demo

### 1. The problem (1 min, no clicking)

"A business question takes days: ask an analyst, wait for a queue, get a
number. Existing BI tools only answer what someone anticipated at build time.
This system answers the question you actually have - and the contribution is
not the LLM call, it is the four things around it."

### 2. Ask a question (2 min)

Ask page → click a starter, or type **"What is total revenue by month?"**

Point at, in this order:
- **The SQL** - always visible, never hidden.
- **The chart** - "the system chose a line chart because it found a date
  column and a numeric column. That rule is stated in the response."
- **Statistics** panel - nulls, ranges, quartiles, outliers.
- **Insight** - "written from the computed statistics."

> **Say this:** "The summary says *template* because there is no API key.
> That label is deliberate - nothing in this system lets a stub answer
> masquerade as a model answer."

### 3. Safety - the strongest part (2 min)

> **Do NOT demo this by asking "delete all customers".** Without an API key
> the stub answers every question with `SELECT * FROM <table> LIMIT 10` - it
> never produces a write, so the safety gate has nothing to refuse and the
> screen shows a perfectly ordinary result. Verified: that path does *not*
> demonstrate the gate.

Demo it through the path that carries real SQL. In a terminal:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/query/execute \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"connection_id":"'"$CID"'","sql":"DELETE FROM customers"}'
```

Or, more reliably in front of an audience, run the adversarial suite:

```bash
cd backend && .venv/Scripts/python -m pytest tests/test_adversarial.py -q
```

Confirmed working: `DELETE`, `DROP TABLE` and `UPDATE` are each rejected with
`gate: safety`, refused outright and never retried.

> **Say this:** "Three defences, independent. The prompt forbids writes. Four
> validation gates run before execution - safety before schema deliberately,
> so `DROP TABLE misspelled` is refused rather than treated as a typo to
> repair. And the connection itself is opened read-only, so even a bug in the
> first two cannot write. 43 of 43 adversarial cases blocked."

### 4. Explain and correct (2 min)

Go back to a working answer → **"Walk me through this query"**

> "Read from the parsed SQL, in evaluation order - FROM before SELECT. Beneath
> it is the model's own prose. Where those two disagree, something is wrong,
> and you can see it."

Then **"This SQL is wrong - fix it"** → edit → **Save correction**.

> "That correction is stored only after it passes the same gates and actually
> runs. Next time someone asks a similar question, it is shown to the model as
> an example - ranked above queries that merely succeeded."

### 5. Dashboard (1 min)

**Pin** → new dashboard → **Dashboards** → open it.

> "Tiles store validated SQL, not the question. Re-asking would cost tokens
> and could return a different query. Every tile is re-validated and re-run on
> open, and one broken tile doesn't take the others down."

### 6. The evaluation (2 min) - the part that shows rigour

```bash
cd backend && .venv/Scripts/python -m evaluation.runner --ablation
```

Let the table render, then point at the **last line**.

> **Say this:** "The system reports that its own result proves nothing. The
> demo schema has 8 tables and the retriever returns 98% of them, so every arm
> scores near 100%. Foreign-key expansion does help consistently - +2.5 recall,
> +10 on all-tables-found - but hybrid fusion shows no benefit at this scale,
> and the k=10 control retrieves the entire schema and also scores 100%. That
> control exists so a win that a bigger k also buys cannot be reported as a
> win for the method. Spider is what makes this question answerable."

---

## Questions you will be asked

**"What accuracy does it achieve?"**
> "None measured. There is no API key in this environment, so the pipeline
> falls back to a stub that does not read the question. Every accuracy gate in
> the proposal is unmet *and unmeasurable*, and I have not estimated one. The
> harness is finished and wired to the real pipeline - one environment
> variable produces the first number."

**"Why not just put the whole schema in the prompt?"**
> "Works at 8 tables, fails at 400 - context limits and cost. Retrieval is
> what makes it scale. And that's research question 1, which is why the
> ablation exists."

**"How do you know it won't drop a table?"**
> "Three independent layers, and the third is enforced by the database, not by
> my code. The connection is opened `mode=ro`."

**"What's the weakest part?"**
> "That nothing has been measured against a real model. Second: the local
> embedder matches on word overlap, so it will not connect 'revenue' to
> 'sales'. Both are stated in every phase document."

**"Did you use AI to build this?"**
> Answer honestly. The engineering decisions, the bugs found, and the refusal
> to report unmeasured numbers are the substance either way.

---

## If something breaks

| Symptom | Fix |
|---|---|
| Ask page empty | Connection not indexed - Connections → Index schema |
| Everything ~2 s slow | Use `127.0.0.1`, not `localhost` (IPv6 fallback) |
| Charts blank | Result is a table shape; open the Statistics panel instead |
| Backend won't start | Port 8000 in use - kill the old process |
| Insight fails | Expected without a key; the table and chart still stand |
| "Delete all customers" returns rows | Correct - the stub never writes. Demo safety via `/query/execute` or the adversarial suite (§3) |

**If the demo dies entirely**: talk over `docs/phase-3.md` (the safety model)
and the ablation table. The written record is the substance.
