# Using the API

The easiest way is the built-in page: **http://localhost:8081/docs**.

For the terminal, first save your key:

```bash
export KEY=your-api-key-from-.env
```

## Is it running?

```bash
curl http://localhost:8081/health/ready
```

## Find jobs

```bash
# best matches first
curl -H "X-API-Key: $KEY" "http://localhost:8081/api/v1/jobs"
# only Germany and the Netherlands
curl -H "X-API-Key: $KEY" "http://localhost:8081/api/v1/jobs?country=DE&country=NL"
# search words
curl -H "X-API-Key: $KEY" "http://localhost:8081/api/v1/jobs?q=migration"
# only jobs with clear visa sponsorship
curl -H "X-API-Key: $KEY" "http://localhost:8081/api/v1/jobs?visa=explicit_sponsorship"
```

Filters: `q`, `country`, `company`, `visa`, `min_score`, `min_salary_eur`, `bookmarked`, `status`.
Sorting: `sort=match_score` (default), `posted_at`, `salary` or `discovered_at`.

## One job in detail

```bash
curl -H "X-API-Key: $KEY" "http://localhost:8081/api/v1/jobs/<job-id>"
```

## Track an application

```bash
# save a job
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  http://localhost:8081/api/v1/applications -d '{"job_id":"<job-id>"}'
# move it along
curl -X PATCH -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  http://localhost:8081/api/v1/applications/<application-id> -d '{"status":"applied"}'
```

Statuses: `saved` → `shortlisted` → `prepared` → `applied` → `interview_scheduled` →
`offer_received` (or `rejected` / `withdrawn`). Every change is kept in `status_history`.

## Dashboard numbers

```bash
curl -H "X-API-Key: $KEY" http://localhost:8081/api/v1/stats/overview
```

## Agent health

```bash
curl -H "X-API-Key: $KEY" http://localhost:8081/api/v1/agents/summary
# check that a worker answers
curl -X POST -H "X-API-Key: $KEY" http://localhost:8081/api/v1/agents/ping
```

## Good to know

- Every `/api/v1` call needs the `X-API-Key` header. Without it you get `401`.
- Too many calls per minute returns `429` (see `RATE_LIMIT_DEFAULT`).
- Every change is recorded in an audit log.
