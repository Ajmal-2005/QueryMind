# Phase 0 - Foundation

Proposal weeks 1-2. Deliverable: *"a running skeleton, health-check endpoint
green, benchmark data loaded."*

---

## What was built

**Repository and tooling.** Git repo, the Appendix A layout, `.gitignore`,
`.env.example`, and a GitHub Actions pipeline running backend lint, backend
format check, backend tests, frontend lint, and frontend build.

**Backend.** FastAPI on SQLAlchemy 2.0. Settings via `pydantic-settings` with
a development default for every value, so the app boots with no configuration.
Structured logging through `structlog` - console output in development, JSON
elsewhere.

**Data layer.** Models for `users`, `connections`, `queries`, and `audit_log`
per Appendix C. Alembic is configured and the initial migration applies and
reverses cleanly.

**Auth.** Registration, login, and `/auth/me`. Bcrypt password hashing, JWT
bearer tokens, and a `require_roles` dependency factory for the RBAC work in
Phase 6.

**Health.** `/api/v1/health` probes the database and Redis and reports each
one separately; `/api/v1/health/live` is a dependency-free liveness probe.

**Frontend.** React + TypeScript on Vite, Tailwind, Zustand for auth state,
TanStack Query for server state, React Router with a protected route. A login
and registration screen, and a dashboard placeholder showing live service
health.

**Evaluation harness.** Dataset loaders for Spider, BIRD, and a committed
custom set; the metrics from proposal section 9; a CLI runner that reports a
summary table and can save per-question JSON.

---

## Verified

- 45 backend tests pass.
- `ruff check` and `ruff format --check` clean.
- Frontend type-checks, lints, and builds.
- Migration applies and reverses against a scratch database.
- Full stack driven in a browser: register → JWT issued → protected route
  renders → health badge live-polls the API through the Vite proxy.
- Harness runs end to end and reports the honest 0% Phase 0 baseline.

## Not verified

- **The Docker Compose stack.** Docker is not installed on the development
  machine. `docker/docker-compose.yml` and `docker/backend.Dockerfile` are
  written to spec but have never been run. This must be confirmed before the
  Phase 1 milestone, since pgvector is a hard dependency of schema indexing.
- **Postgres and pgvector paths.** Everything so far ran on SQLite.
- **Spider and BIRD loading against real files.** The loaders are tested for
  their failure path (a clear "not found, download from here" message) but not
  against the actual archives, which are not downloaded.

---

## Decisions

**SQLite fallback for the app database.** Postgres with pgvector is the
target and the Compose stack provides it. But making Docker a hard requirement
to run anything would have blocked all of Phase 0 on this machine. The app
reads `DATABASE_URL`, defaults to SQLite, and switches to Postgres by
changing one environment variable. Tests run on SQLite and stay fast and
dependency-free. The cost: pgvector-specific code cannot be exercised locally,
which is fine until Phase 1 needs it.

**`create_all` on SQLite, Alembic everywhere else.** Local development should
not need a migration step to get a working database; deployment should never
use anything but migrations. `main.py` branches on the dialect.

**First registered user becomes admin.** A fresh instance needs some way to
get an administrator without a seed script or a hardcoded password.

**Identical error for unknown email and wrong password.** Distinguishing them
turns the login endpoint into an account-enumeration oracle.

**Bcrypt's 72-byte limit raises rather than truncates.** Silently hashing a
prefix would give a user a false sense of password strength.

**Result comparison normalizes numeric types.** Postgres returns
`Decimal('3.0')` where MySQL returns `3`; both are the same answer, so
`execution_match` compares canonical string forms. Without this the accuracy
numbers would be wrong in the system's favour on some dialects and against it
on others.

**Recovery rate is measured over queries that needed correction**, not over
all queries - otherwise adding easy questions to the benchmark would inflate
the number.

**Python 3.10 compatibility.** The proposal specifies 3.11+; only 3.10.9 is
installed here. Nothing in the codebase needs 3.11, so the code targets 3.10
and the Docker image pins 3.11.

---

## Milestone gate

> Week 2 - Infrastructure complete - *CI green, services healthy.*

CI is written and every check it runs passes locally. Services are healthy on
the SQLite/no-Docker path. The gate is **met with one exception**: "services
healthy" has not been demonstrated for the Postgres, pgvector, and Redis
containers, because Docker is not installed.

---

## Before Phase 1

1. Install Docker Desktop and bring up the Compose stack.
2. Confirm pgvector is present: `CREATE EXTENSION vector;` succeeds.
3. Point `DATABASE_URL` at Postgres and run `alembic upgrade head`.
4. Confirm `/api/v1/health` reports both database and Redis `ok`.
5. Download Spider and BIRD into `backend/evaluation/data/`.
