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
The same role found on several boards is shown once (add `include_duplicates=true` to see all).
Sorting: `sort=match_score` (default), `posted_at`, `salary` or `discovered_at`.

## One job in detail

```bash
curl -H "X-API-Key: $KEY" "http://localhost:8081/api/v1/jobs/<job-id>"
```

## Run everything now (find, score, check visa and salary)

```bash
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  http://localhost:8081/api/v1/pipeline/run -d '{}'
```

To re-score stored jobs without fetching, for example after editing your profile, send
`{"analyse_only": true}`. To redo one job from scratch:

```bash
curl -X POST -H "X-API-Key: $KEY" http://localhost:8081/api/v1/jobs/<job-id>/reprocess
```

Unchanged jobs are skipped automatically, so running it often is cheap.

## Find new jobs only

Discovery runs every day by itself. To run it now:

```bash
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  http://localhost:8081/api/v1/discovery/run -d '{}'
```

It returns a `task_id`. Check progress with
`GET /api/v1/agents/tasks/<task_id>`. A full run takes about a minute.

## Job sources

```bash
# list sources and how many active jobs each has
curl -H "X-API-Key: $KEY" http://localhost:8081/api/v1/sources
# add a company that uses Greenhouse (the token is in its jobs URL: boards.greenhouse.io/<token>)
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  http://localhost:8081/api/v1/sources \
  -d '{"key":"greenhouse:acme","name":"Acme","connector":"greenhouse","config":{"board_token":"acme"}}'
# turn a source off
curl -X PATCH -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  http://localhost:8081/api/v1/sources/<source-id> -d '{"enabled":false}'
# see the settings each connector accepts
curl -H "X-API-Key: $KEY" http://localhost:8081/api/v1/discovery/connectors
```

Connectors: `greenhouse` (`board_token`), `lever` (`site`), `arbeitnow`,
`adzuna` (needs keys in `.env`), `rss` (`feed_url`).

## Saved searches

```bash
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  http://localhost:8081/api/v1/candidate/search-configs \
  -d '{"name":"Nordics","keywords":["cloud architect","platform architect"],
       "countries":["SE","DK","FI"],"schedule_cron":"0 7 * * 1-5"}'
```

`schedule_cron` is a standard cron line in UTC (`0 7 * * 1-5` = weekdays at 07:00).

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

## Prepare an application (drafts only)

```bash
# ask the agent for a tailored CV, cover letter, recruiter message and interview prep
curl -X POST -H "X-API-Key: $KEY" http://localhost:8081/api/v1/applications/<application-id>/prepare
# read the drafts
curl -H "X-API-Key: $KEY" http://localhost:8081/api/v1/applications
# edit a draft (this clears any earlier approval)
curl -X PATCH -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  http://localhost:8081/api/v1/applications/<application-id>/drafts -d '{"cover_letter_draft":"..."}'
# approve the drafts (a record for you; nothing is sent)
curl -X POST -H "X-API-Key: $KEY" http://localhost:8081/api/v1/applications/<application-id>/approve-drafts
# download the tailored CV (Word file)
curl -H "X-API-Key: $KEY" -o cv.docx http://localhost:8081/api/v1/applications/<application-id>/tailored-cv
```

You send applications and messages yourself. The system never does.

## Notifications

```bash
curl -H "X-API-Key: $KEY" "http://localhost:8081/api/v1/notifications?unread_only=true"
curl -X POST -H "X-API-Key: $KEY" http://localhost:8081/api/v1/notifications/read
```

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
