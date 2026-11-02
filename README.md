# EU Job Intelligence

A self-hosted, multi-agent platform that discovers European Cloud Architect opportunities,
scores them against your profile, analyses visa sponsorship and salary evidence, and
prepares application drafts. **Nothing is ever submitted or sent without your explicit
approval.** It runs on local models (Ollama), so no paid LLM API is needed.

- Architecture, service boundaries, data model and hardware sizing: [docs/architecture.md](docs/architecture.md)
- Problems and fixes: [docs/troubleshooting.md](docs/troubleshooting.md)
- Interactive API docs (once running): http://localhost:8081/docs

## Build status

| Phase | Scope | Status |
|---|---|---|
| 1. Foundation | Schema + migrations, FastAPI backend, Postgres/pgvector, Redis, Celery skeleton, Compose | **Done**, tested |
| 2. Job discovery | Greenhouse/Lever/Adzuna/EURES/RSS connectors, dedup, expiry, scheduling | Not started |
| 3. AI intelligence | Ollama, CV parsing, matching, visa, salary, LangGraph orchestrator | Not started |
| 4. Frontend | Next.js dashboard | Not started |
| 5. Kubernetes | k3d manifests + Helm chart | Not started |
| 6. Observability | Prometheus/Grafana dashboards, failure-recovery tests | Partial (`/metrics` endpoint exists) |

## Quick start (Docker Compose)

Requirements: Docker Desktop (or Engine) with Compose v2 and at least 4 GB of memory
assigned to Docker. See [hardware requirements](docs/architecture.md#6-local-hardware-requirements).

```bash
cd eu-job-intelligence
cp .env.example .env
```

Edit `.env` and replace every `CHANGE_ME` value. To generate secrets:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Start the stack. This builds the image, starts Postgres and Redis, runs migrations, then
starts the API and the discovery worker:

```bash
docker compose up -d --build
```

```bash
docker compose ps
```

Load the sample candidate profile (from the brief) and 8 **fictional** sample jobs:

```bash
docker compose exec backend python -m scripts.seed
```

Try the API. Replace `$KEY` with a value from `API_KEYS` in `.env`:

```bash
curl -s localhost:8081/health/ready
```

```bash
curl -s -H "X-API-Key: $KEY" localhost:8081/api/v1/candidate | python3 -m json.tool
```

```bash
curl -s -H "X-API-Key: $KEY" "localhost:8081/api/v1/jobs?country=DE&country=NL" | python3 -m json.tool
```

### Fill in your work-authorization details

The seeded profile leaves citizenship, EU work authorization, sponsorship need and
relocation **unset on purpose**. The agents never guess these values. `GET
/api/v1/candidate` lists what is missing in `profile_completeness`. To set them:

```bash
curl -s -X PATCH -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  localhost:8081/api/v1/candidate \
  -d '{"full_name":"Your Name","citizenship":["IN"],"has_eu_work_authorization":false,
       "requires_visa_sponsorship":true,"open_to_relocation":true,"min_salary_eur":80000}'
```

Upload a resume (PDF or DOCX, max `MAX_UPLOAD_MB`):

```bash
curl -s -H "X-API-Key: $KEY" -F file=@/path/to/cv.pdf -F version_label=main \
  localhost:8081/api/v1/candidate/resumes
```

### Optional: local LLM

Phase 3 agents use Ollama. On Apple Silicon, run it natively so it can use the GPU:

```bash
brew install ollama
```

```bash
ollama serve
```

```bash
ollama pull llama3.2:3b && ollama pull nomic-embed-text
```

On Linux, or to keep everything in containers (CPU-only on macOS), use the bundled service
and set `OLLAMA_BASE_URL=http://ollama:11434` in `.env`:

```bash
docker compose --profile ollama up -d ollama
```

```bash
docker compose exec ollama ollama pull llama3.2:3b
```

## Running tests

Tests run on the host against the Compose Postgres and Redis. They use a separate
`eujobs_test` database and Redis DB 15, so your data is untouched.

```bash
uv sync
```

```bash
docker compose up -d postgres redis
```

```bash
uv run pytest -v
```

`uv run pytest tests/unit` needs no services.

## Database migrations

```bash
docker compose run --rm migrate alembic upgrade head
```

To create a new migration after changing models in `database/models/`:

```bash
uv run alembic revision --autogenerate -m "describe change"
```

## Backups

```bash
scripts/backup_db.sh
```

```bash
scripts/restore_db.sh backups/eujobs-<timestamp>.dump
```

`backup_db.sh` keeps the newest 14 dumps (`KEEP=n` to change). Schedule it with cron or
launchd for daily backups.

## API overview

All `/api/v1/*` routes need `X-API-Key` and are rate limited (`RATE_LIMIT_DEFAULT`).
Every mutation is written to `audit_logs`.

| Area | Endpoints |
|---|---|
| Health | `GET /health/live`, `GET /health/ready`, `GET /metrics` |
| Candidate | `GET/POST/PATCH /candidate`, skills, experiences, resumes, search-configs |
| Jobs | `GET /jobs` (filters: `q`, `country`, `company`, `visa`, `min_score`, `min_salary_eur`, `bookmarked`, `sort`), `GET /jobs/{id}` |
| Applications | `GET/POST /applications`, `PATCH/DELETE /applications/{id}` |
| Monitoring | `GET /stats/overview`, `GET /agents/summary`, `GET /agents/executions`, `POST /agents/ping`, `GET /agents/tasks/{id}` |

## Repository layout

```
common/          settings, JSON logging, enums
database/        SQLAlchemy models, Alembic migrations, session factory
backend/         FastAPI app: routes, schemas, services, security, middleware
workers/         Celery app + tasks (one image, one queue per worker type)
connectors/      job-source connectors + normalisation/dedup helpers
agents/          LangGraph orchestrator and agents (Phase 3)
frontend/        Next.js dashboard (Phase 4)
infrastructure/  Dockerfiles, Kubernetes, Helm
monitoring/      Prometheus + Grafana (Phase 6)
scripts/         seed, backup, restore
data/sample/     sample candidate profile and fictional jobs
tests/           unit + integration
```

## Responsible use

- Connectors use only public APIs, RSS feeds and public ATS job boards. They respect
  robots.txt and per-source rate limits, and never log in, solve CAPTCHAs or evade bot
  protection.
- Visa classifications always cite evidence (URL + quote). A company is never treated as
  a sponsor because it employs international staff.
- Salary *estimates* are kept separate from advertised salaries, and their assumptions
  are always listed.
- Interview likelihood is a heuristic estimate, not a prediction backed by hiring data.
