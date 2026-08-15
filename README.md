# NLQ Analytics Platform

Ask a relational database questions in plain English; get back validated SQL,
a result table, a chart, and a written summary.

Capstone implementation of [`proposal.md`](proposal.md). **Current state:
Phase 0 (Foundation) complete.**

---

## Quick start (no Docker required)

### Backend

```bash
cd backend && python -m venv .venv && .venv/Scripts/python -m pip install -r requirements-dev.txt
```

```bash
cd backend && .venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

The app defaults to a local SQLite file, so nothing else needs to be running.
Open <http://localhost:8000/docs> for the API, or
<http://localhost:8000/api/v1/health> for the health gate.

### Frontend

```bash
cd frontend && npm install && npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` to port 8000, so there is no
CORS setup in development. The first account you register becomes the admin.

### With Docker (Postgres + pgvector + Redis)

```bash
docker compose -f docker/docker-compose.yml up --build
```

Then point the backend at Postgres by setting `DATABASE_URL` in `.env` — see
[`.env.example`](.env.example).

---

## Verifying the build

```bash
cd backend && .venv/Scripts/python -m pytest
```

```bash
cd backend && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .
```

```bash
cd frontend && npm run lint && npm run build
```

CI runs exactly these three on every push.

---

## Evaluation harness

```bash
cd backend && .venv/Scripts/python -m evaluation.runner --dataset custom
```

Reports execution accuracy, valid-SQL rate, schema-linking recall, correction
recovery rate, and latency percentiles. Until the Phase 2 pipeline lands the
predictor is a stub, so a 0% baseline is the expected and correct output.

The custom 10-question e-commerce set is committed. Spider and BIRD are large
and licence-gated, so they are not vendored — extract them into
`backend/evaluation/data/spider/` and `backend/evaluation/data/bird/` and the
loaders will find them. Running without them prints exactly what is missing.

---

## Layout

```
backend/
  app/
    api/v1/        route handlers (health, auth)
    core/          config, database, security, logging
    models/        SQLAlchemy models
    schemas/       Pydantic contracts
    services/      pipeline stages — populated from phase 1 onward
    workers/       Celery tasks (phase 1+)
  alembic/         migrations
  evaluation/      Spider/BIRD/custom harness
  tests/
frontend/
  src/
    api/           typed HTTP client
    components/    shared UI
    pages/         routed screens
    stores/        Zustand state
docker/            compose stack and backend image
docs/              phase notes and decisions
```

---

## Phase status

| Phase | Scope | State |
|---|---|---|
| 0 | Foundation: repo, CI, auth, health, eval harness | **Done** |
| 1 | Connection manager and schema introspection | Not started |
| 2 | NL→SQL core: intent, retrieval, generation | Not started |
| 3 | Validation gates, sandboxed execution, self-correction | Not started |
| 4 | Analytics: profiling, charts, narrative insight | Not started |
| 5 | Conversation and learning from corrections | Not started |
| 6 | Hardening, benchmarks, ablations | Not started |
| 7 | Report, deck, demo | Not started |

See [`docs/phase-0.md`](docs/phase-0.md) for what was built and the decisions
behind it.

---

## Environment notes

Built and verified on Python 3.10 and Node 20. The proposal specifies Python
3.11+; the code is 3.10-compatible and the Docker image pins 3.11, so both
work. Docker was not available on the development machine, so the Compose
stack is written but unverified — see `docs/phase-0.md`.
