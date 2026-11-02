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
