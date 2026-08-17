# Phase 4 - Analytics & Visualization

Weeks 10-11. Features F11-F18, plus the Redis result cache deferred from
Phase 3.

The deliverable: every query comes back with a table, an appropriate chart,
and a written summary.

---

## What was built

### `services/analytics/` - the analytics stage

| Module | Feature | What it does |
|---|---|---|
| `profile.py` | F14 | Type inference and descriptive statistics per column |
| `charts.py` | F11/F12 | Rule-based chart selection; axis options for the override |
| `outliers.py` | F15 | IQR and z-score flagging, with fences reported |
| `trends.py` | F16 | Period-over-period deltas, growth rates, moving average |
| `masking.py` | - | PII detection and masking on the outbound path |
| `narrative.py` | F13 | LLM summary from the profile, plus an offline template narrator |
| `export.py` | F17 | CSV, JSON, XLSX, PDF |
| `analyze.py` | - | Composes profile → chart + outliers + trend |

**Profiling is the load-bearing piece.** Chart selection, outlier detection
and trend analysis all read the profile rather than the rows, so type
inference happens once instead of three times with three chances to disagree.

Inference reads values, not declared types, because SQLite has no date type -
a `DATE` column arrives as `str`. Each column records *how* it was classified
in `inferred_from`, surfaced as a tooltip in the statistics table, so a wrong
call is visible rather than mysterious.

### Chart selection

Ordered rules, first match wins, every outcome carrying the sentence that
produced it:

1. one row, one number → **KPI**
2. a date column + numerics → **line** (split by a category if there is one)
3. one category + numerics, ≤25 distinct → **bar** (pie offered when ≤6
   slices, one measure, nothing negative)
4. two bare numerics → **scatter**
5. anything else → **table**

A table is never *wrong*, only less illuminating, which makes it the right
floor for a system that must not present data misleadingly.

### PII masking

F13 is the first point in this system where row *values*, not schema names,
leave the deployment. Two independent detectors run:

- **Column names** - `full_name`, `email`, `dob`, `api_key`. Catches data with
  no distinctive format. `address_id` and `email_count` are explicitly
  exempted; masking a foreign key would break the narrator's grasp of joins.
- **Value patterns** - email, Luhn-checked card, national id, IBAN, IP, and
  grouped phone numbers. Catches PII sitting in an innocently named column.

Masking replaces with a type token (`<email>`), not a partial mask. Partial
masking leaks the domain, the last four digits, the name length - and the
narrator never needs the value, only the shape.

Numbers, dates and categories pass through untouched. Masking the measures
would leave nothing to summarise.

### Narrative

The model receives **exact statistics computed here** plus 20 masked sample
rows. It is told not to derive figures from the sample. A model handed 10,000
raw rows would have to add them up itself and would sometimes get it wrong
while sounding equally confident; this way every number in the summary traces
to arithmetic this process did.

`TemplateNarrator` is the offline fallback and - unlike the SQL layer's stub -
it is not a placeholder. Statistical narration is a template problem, so it
writes a genuinely correct summary from the profile with no API key. It is
labelled `template` everywhere it appears, and the UI says "computed from the
statistics - no language model was called".

### Result cache (deferred from Phase 3)

`services/cache/`. Redis when `REDIS_URL` is set, an in-process TTL map
otherwise, `NullCache` when disabled.

Safe to cache at all because every query reaching execution has passed the
safety gate, so it is a read. Nothing writes to a target database, which means
a cached result can only ever be *stale*, never wrong about an operation that
happened. Handled by being short (300 s) and honest: `cached: true` rides on
every result so the UI can say so and no benchmark can mistake a 2 ms cache
hit for query performance.

Keyed on the **validated SQL**, hashed - SQL is long, contains characters
Redis keys handle badly, and would otherwise put user data into key names that
appear in logs. Invalidated on re-index and on connection delete.

### Dashboards (F18)

`Dashboard` + `DashboardTile` models, migration `c4e1a90f7b23`.

Tiles store SQL, not the question: re-asking on every open would re-run
generation, cost tokens each time, and could return a different query than the
one the user pinned.

Every tile is re-validated on every refresh. A query that was safe when pinned
is not assumed safe now - the schema may have been re-indexed. Refresh is
strict at the gate and forgiving at the tile: one broken tile shows as a
broken tile beside the working ones.

### API

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/query` | now returns `analysis` |
| `POST` | `/query/execute` | now returns `analysis` |
| `POST` | `/query/insight` | narrative summary (F13) |
| `POST` | `/query/analyze` | re-profile without generating |
| `POST` | `/query/export` | CSV / JSON / XLSX / PDF (F17) |
| `GET` | `/query/cache` | cache statistics |
| `POST/GET/PATCH/DELETE` | `/dashboards…` | dashboard and tile CRUD |
| `POST` | `/dashboards/{id}/refresh` | re-run every tile |

Every endpoint that executes SQL goes through one helper that runs the same
four gates. An export is not a way around the validation layer.

### Frontend

Recharts installed. `ChartView`, `ChartControls`, `ProfilePanel`,
`InsightPanel`, `ExportMenu`, `PinToDashboard`, `ResultView`, and a
`DashboardsPage`. The `P4` badge is off the nav item.

`ResultView` is shared by the Ask page and reused for tiles, so the two cannot
drift apart.

---

## Verified

**460 backend tests pass** (up from 344), ruff clean, frontend builds and
lints clean.

Exercised against the running app with the seeded demo database:

- A 24-month revenue query profiled as `month` temporal + `revenue` numeric,
  selected **line**, computed the trend (`-98.7% from 289,807.47 to 3,795.74`)
  and flagged 2 outliers.
- The Ask page rendered a scatter chart with working axis pickers, the
  statistics panel, the outlier callout, and a template-written insight
  correctly labelled as not model-written.
- Pinned that result to a new dashboard from the result view; the dashboard
  refreshed in **16 ms** with the chart rendered and the row marked `cached`.
- All four export formats return files with the correct magic bytes
  (`%PDF`, `PK`, UTF-8 BOM, `[`) and a `Content-Disposition` filename.
- `DROP TABLE` and `DELETE` are refused by `/analyze`, `/insight`, `/export`
  and tile creation, naming the safety gate.
- A dashboard is 404 to anyone but its owner.
- Deleting a connection leaves its tile in place, reporting the failure, while
  sibling tiles still render.

---

## Not verified

Carried forward and still true:

1. **No `ANTHROPIC_API_KEY`.** `AnthropicNarrator` has **never been called**.
   Every narrative produced so far came from `TemplateNarrator`. The masking
   layer's *transit* behaviour is tested against a scripted provider, never
   against a real API call.
2. **Redis has never run.** `RedisCache` is written and unexercised; all cache
   testing is against `MemoryCache`. `MemoryCache` is also wrong for more than
   one worker, which is exactly why Redis is the deployment target.
3. **No Docker, no Postgres, no MySQL** - unchanged from Phase 3.
4. **PDF chart embedding is untested end to end.** The server-side path is
   tested with no image; the browser's SVG→PNG→PDF round trip has not been run
   with a real chart.
5. **Retrieval at scale** - the demo schema has 8 tables. Profiling has never
   seen a result wider than 5 columns or longer than a few thousand rows.
6. **No accuracy figure.** Unchanged and unmeasurable without a key.

---

## Decisions

| Decision | Why |
|---|---|
| **Stdlib `statistics`, not Pandas/NumPy** | The proposal names Pandas/NumPy/SciPy and PROGRESS.md claimed they were installed - they were not. Results are capped at 10,000 rows, and the arithmetic is ~100 lines of `statistics`. Type inference had to be hand-written anyway, because Pandas would fight us over SQLite's dynamic typing. Avoids a ~50 MB dependency for work that does not need it. **This deviation must be stated in the final report.** |
| **Chart selection is rule-based** | Fully determined by result shape. An LLM round trip would cost more than the entire rest of the analytics stage, and a wrong choice is cosmetic - one click fixes it. |
| **Cardinality, not a distinct/total ratio, decides "categorical"** | Found during testing: every `GROUP BY` produces exactly one row per key, so a ratio test scores 1.0 and classifies the grouping column as free text - the single most common result shape this product produces. Length separates free text from labels far better than counting does. |
| **Two outlier methods, both reported** | They disagree usefully. Revenue and counts are right-skewed, and one large value inflates the standard deviation enough to hide its own z-score; quartiles are unmoved by it. A value both methods flag deserves attention; one only the z-score flags usually does not. |
| **Trend direction from a least-squares slope** | Every period votes, so a modest final uptick cannot declare a declining series to be growing. Not robust to a large outlier - least squares never is - and a series that genuinely spiked *should* be reported as having spiked. |
| **Repeated periods decline a trend rather than aggregate** | A detail listing is not a time series. Averaging it here would invent a series the user never asked for. |
| **Narrative is a separate endpoint, not part of `/query`** | It is the one analytics step costing an API call. Holding the table and chart back while waiting on prose would make the product feel slower than it is. |
| **The narrator gets statistics, not raw rows** | Every number in the summary traces to arithmetic this process did, rather than to a model's mental addition. |
| **The offline narrator is real, not a stub** | The product's promise - every query returns a written summary - holds with no API key. Labelled `template` so no report can misattribute it. |
| **Insight/export re-fetch rows server-side** | The server will not narrate or export data it has not read out of the database itself, and 10,000 rows never travel upstream from the client. |
| **PNG in the browser, PDF on the server** | The chart is a Recharts SVG that only exists in the browser; redrawing it server-side would mean a second charting implementation that could disagree with what the user saw. So the browser serialises its own chart and posts it up for the PDF. |
| **Tiles are rows, not a `layout` JSON blob** | Appendix C specifies `dashboards (id, user_id, name, layout jsonb)`. A tile holds SQL that gets *executed*; rows can be counted, indexed, cascaded and audited individually, and one malformed tile cannot take the dashboard down. `layout` survives for grid positions, which genuinely are unstructured. |
| **Dashboards refresh on open, nothing precomputed** | A dashboard quietly showing last Tuesday's numbers is worse than no dashboard. The cache absorbs the cost of several people opening the same board. |
| **Tiles re-validated on every refresh** | Safe-when-pinned is not safe-now; the schema may have moved. |

---

## Bugs found during verification

**1. Masking leaked PII through the profile.** *(security, serious)*

The sample rows were masked before entering the narrative prompt, but
`describe_profile` rendered each categorical column's `top_values`
straight from the unmasked profile. A `full_name` column's most common
values - real names - went into the prompt verbatim, defeating the masking
entirely.

Fixed: the profile's rendered values now go through the same masking. A
column the name-rule flags reports `N distinct; values withheld (name)`;
values in unflagged columns pass through `mask_value`. Numeric aggregates are
untouched - masking those would leave nothing to summarise. Two regression
tests cover it.

The general lesson, worth stating in the report: *masking has to be applied at
the boundary, not to one object that happens to cross it.* The profile carries
row data every bit as much as the sample does.

**2. The phone-number pattern matched any long run of digits.**

`1234567890123456` and `2024-01-15` were both masked - the first as a phone
number after failing the payment-card Luhn check, the second because an ISO
date is grouped exactly like a phone number. Masking dates would have hidden
the axis of every trend the product draws.

Fixed: a phone number now requires either a leading `+` or actual separators,
plus a 9-15 digit count and an explicit ISO-date exclusion. A bare
`5551234567` is deliberately *not* matched - it is indistinguishable from an
order id, and the column-name rule covers `phone` columns.

**3. Every `GROUP BY` key was classified as free text.**

See the decisions table. The distinct/total ratio guard, intended to exclude
identifier columns, rejected exactly the columns this product charts most
often. Caught by the bar-chart test.

**4. A docstring claimed more than the code delivered.**

The trend module claimed a least-squares slope could not be swayed by a single
end spike. It can - least squares is not robust to outliers. The test asserting
it failed. Both the docstring and the test were corrected to state what is
actually true rather than weakening the test to match the claim.

---

## Milestone gate

Proposal target for weeks 10-11: *every query returns a table, an appropriate
chart, and a written summary.*

**Met.** Confirmed in the running app: a query returns rows, a chart selected
from the result shape with the reason stated, and a written summary - with
statistics, outliers and trend available behind one click.

Two qualifications for the report:

- The summary is currently written by the template narrator, not by a model.
  The LLM path is written and unexercised.
- "Appropriate" is measured against the rule set here, not against human
  judgement. No study was run on whether users agree with the choices.

---

## Before Phase 5

1. **Set `ANTHROPIC_API_KEY`.** It now unblocks two things: real SQL
   generation *and* the first genuine narrative, which is also the only way to
   confirm the masking layer behaves on a live outbound call.
2. Redis, if Docker becomes available - it would move `RedisCache` and the
   multi-worker cache story from written to exercised.
3. Phase 5 (`F19`-`F25`) extends `intent.py`, which Phase 4 did not touch.
