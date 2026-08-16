# Demo questions

Every question below was run against the live app and the SQL checked. Times
are from a free-tier Gemini key and vary; ask them once before presenting so
the result cache makes repeats instant.

---

## Open with these — they land every time

| Question | Shows | Rows |
|---|---|---|
| **Which product categories generated the most revenue?** | 3-table join, aggregation, bar chart | 12 |
| **Which customers have never placed an order?** | LEFT JOIN anti-join — the query people expect it to fail | 11 |
| **Show monthly revenue trend for completed orders** | Date grouping, line chart, trend analysis | 24 |
| **Which suppliers have the longest average lead time?** | Junction table reached by FK expansion | 5 |

**"Which customers have never placed an order?"** is the single best opener.
It produces:

```sql
SELECT c.id, c.full_name, c.email
FROM customers AS c
LEFT JOIN orders AS o ON c.id = o.customer_id
WHERE o.id IS NULL
```

> *"That's an anti-join. Nobody phrases the question that way, and it's the
> shape people assume these systems get wrong."*

**"Which suppliers have the longest average lead time?"** is the one to
explain retrieval with — `product_suppliers` is a junction table with a
cryptic name that no retriever ranks highly. It arrives through foreign-key
expansion, and the provenance panel marks it with `↳`.

---

## Also verified

- What is the average order value by region?
- Which 5 customers have spent the most in total?
- How many orders are in each status?
- Top 5 products by price
- How many customers do we have?

---

## Feature showcases

**Business glossary (F24)** — ask:

> **How many active customers are there per region?**

"Active customer" is not in the schema. The glossary supplies
`EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.id)`, and the
provenance panel lists the definition it applied.

**Clarification (F20)** — ask:

> **show me something**

Returns a targeted question plus three clickable rewrites. Click one.

**Multi-turn (F19)** — two turns, not three:

> **What was total revenue by month?**
> then **break that down by region**

Resolves to *"What was total revenue by month?, grouped additionally by:
region"* and the badge reads `follow-up`.

⚠️ **Stop at two.** A third turn resolves against the raw previous question
rather than the accumulated one, so "just the north region" loses the revenue
context from two turns back. Session history stores the question as typed, not
as resolved — see *Known gaps*. Demo two turns; it works cleanly.

**Safety** — do **not** ask "delete all customers". The model correctly
refuses to write one, so nothing is blocked and it looks like nothing
happened. Use the adversarial suite instead:

```bash
cd backend && .venv/Scripts/python -m pytest tests/test_adversarial.py -q
```

---

## Avoid these

| Question | Why |
|---|---|
| *Which products have never been ordered?* | Correct SQL, but every product has been ordered — returns 0 rows and looks broken |
| *Delete all customers* | The model won't generate a write, so the gate never fires |
| Anything with "best" or "top" and no measure | Answers with an assumption rather than asking — fine, but not the demo you want |

---

## If a question comes back wrong

It happens — output varies between runs even at temperature 0, because query
history feeds new few-shot examples into the prompt each time.

**Turn it into the feature it is.** Click **"This SQL is wrong — fix it"**,
correct the SQL, save. Then re-ask the question: the correction is retrieved as
an example, ranked above anything that merely succeeded, and the provenance
panel shows it was used. That is F22, and it demos better from a real failure
than from a rehearsed success.
