# Developer Guide

## Project layout

```
common/          settings, logging, shared lists (enums)
database/        tables (models), migrations, DB connection
backend/         the API: routes, request/response models, security
workers/         background workers (Celery)
connectors/      job board connectors and cleanup helpers
agents/          the AI agents (Phase 3)
frontend/        the dashboard (Phase 4)
infrastructure/  Docker, Kubernetes, Helm
tests/           unit and integration tests
scripts/         seed data, backup, restore
data/sample/     sample profile and made-up jobs
```

## Run the tests

```bash
uv sync                                  # install Python packages
docker compose up -d postgres redis      # integration tests need these
uv run pytest                            # all tests
uv run pytest tests/unit                 # fast tests, no services needed
```

Tests use their own database (`eujobs_test`), so your data is safe.

## Dashboard (frontend)

The dashboard is a Next.js app in `frontend/`. Node isn't required locally: the Docker build
installs packages, type-checks (`tsc --noEmit`) and builds it.

```bash
docker compose up -d --build frontend
```

For live editing with Node 20 installed:

```bash
cd frontend && npm ci && BACKEND_INTERNAL_URL=http://localhost:8081 npm run dev
```

Then open http://localhost:3001. The browser calls `/backend/*` on the same origin, which
Next.js forwards to the API, so no CORS setup is needed. The API key lives only in the
browser's local storage.

## Code style

```bash
uv run ruff check .
uv run ruff format .
```

## Changing the database

1. Edit a model in `database/models/`.
2. Create a migration:
   ```bash
   uv run alembic revision --autogenerate -m "what changed"
   ```
3. Read the generated file in `database/migrations/versions/`.
4. Apply it:
   ```bash
   uv run alembic upgrade head
   ```

## Backups

```bash
scripts/backup_db.sh                               # saves to backups/
scripts/restore_db.sh backups/eujobs-<time>.dump   # asks before overwriting
```

## Logs

```bash
docker compose logs -f backend
docker compose logs -f job-discovery-worker
```

Logs are JSON. Every API request has a `request_id`, also returned in the `X-Request-ID` header.

## Rules for contributors

- No secrets in code. Use `.env`.
- New job sources must use public APIs or feeds and respect robots.txt.
- Agents must never send, submit or change user data without approval.
- Do not claim a feature works until a test proves it.
