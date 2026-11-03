# Troubleshooting

## `bind: address already in use` on `docker compose up`

Another stack is using the host port. Change `API_PORT`, `POSTGRES_PORT` or `REDIS_PORT`
in `.env` (defaults: 8081, 5433, 6380), and update `DATABASE_URL`/`REDIS_URL` in `.env`
to match if you run tests or Alembic from the host.

## `migrate` exits with an error and `backend` never starts

`backend` and the workers wait for `migrate` to finish successfully. To see why it failed:

```bash
docker compose logs migrate
```

Common causes:

- Wrong `POSTGRES_PASSWORD`. Postgres keeps the password from the **first** start of the
  volume, so changing `.env` later has no effect. Either restore the old password, or
  delete the volume (this deletes all data): `docker compose down -v`.
- `type "vector" does not exist`: the image is not `pgvector/pgvector`. The migration
  runs `CREATE EXTENSION vector`, which needs the pgvector build of Postgres.

## API returns 401 for every request

Send the header `X-API-Key: <one of API_KEYS>`. If `API_KEYS` is empty, the backend logs
`no_api_keys_configured` at startup and rejects all `/api/v1` calls. This fails closed
by design.

## `/health/ready` returns 503

The response body says which dependency failed (`postgres` or `redis`). Check
`docker compose ps` and the logs of that service.

## Worker shows `unhealthy`

```bash
docker compose logs job-discovery-worker
```

Usually it cannot reach Redis (wrong `REDIS_PASSWORD`). To check the worker end to end:

```bash
curl -s -X POST -H "X-API-Key: $KEY" localhost:8081/api/v1/agents/ping
```

Then fetch `/api/v1/agents/tasks/<task_id>`. The state should be `SUCCESS`.

## Dashboard says the key was not accepted

Use a value from `API_KEYS` in `.env` (not the Postgres or Redis password). If you changed
`API_KEYS`, restart the backend with `docker compose up -d backend`.

## Dashboard loads but shows errors or empty pages

Check that the backend is healthy (`docker compose ps`). The dashboard forwards `/backend/*`
to `http://backend:8000` inside Docker. If you renamed the service, rebuild the frontend
with a matching `BACKEND_INTERNAL_URL` build argument.

## Integration tests are skipped

`tests/conftest.py` skips integration tests when Postgres or Redis is unreachable. Start
them with `docker compose up -d postgres redis` and make sure `DATABASE_URL`/`REDIS_URL`
in `.env` point at the host ports (`localhost:5433`, `localhost:6380`).

## Jobs have scores but `semantic_similarity` is empty

Ollama isn't reachable or the models aren't pulled. The pipeline then uses rule-based
scoring only (see the `embedding` step in `GET /api/v1/agents/executions`). Start
Ollama, pull `nomic-embed-text` and your chat model, then re-score with
`POST /api/v1/pipeline/run {"analyse_only": true, "force": true}`.

## A resume shows `parse_error`

The PDF is probably scanned (an image). Upload a DOCX or a text-based PDF, or re-run
parsing with `POST /api/v1/candidate/resumes/<id>/parse`.

## Ollama is slow or runs out of memory

- On macOS, Docker containers cannot use the Apple GPU. Run Ollama natively and set
  `OLLAMA_BASE_URL=http://host.docker.internal:11434`.
- Use a smaller model (`LLM_CHAT_MODEL=llama3.2:3b`). A 7–8B model needs about 6–8 GB of
  free RAM.
- Raise the Docker Desktop memory limit (Settings → Resources) if you run Ollama in a
  container.

## Resetting everything

This deletes the database, Redis data, uploaded resumes and downloaded models:

```bash
docker compose down -v
```
