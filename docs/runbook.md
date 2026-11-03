# Operations Runbook

How to run, check, maintain and fix EU Job Intelligence. Each section starts with the
quickest check, then the fix. Commands assume you are in the `eu-job-intelligence/`
folder.

- **Docker Compose** is the default way to run it (sections 1–6).
- **Kubernetes (k3d)** has its own section ([7](#7-kubernetes-k3d)).

Throughout, `$KEY` is your API key:

```bash
export KEY=$(grep ^API_KEYS= .env | cut -d= -f2 | cut -d, -f1)
```

---

## 1. At a glance

| What | Where |
|---|---|
| Dashboard | http://localhost:3001 |
| API + interactive docs | http://localhost:8081/docs |
| Health (no key) | http://localhost:8081/health/ready |
| Metrics (Prometheus format) | http://localhost:8081/metrics |
| Database (host) | `localhost:5433` (user and password in `.env`) |
| Redis (host) | `localhost:6380` (password in `.env`) |

| Container | Role | Healthy means |
|---|---|---|
| `postgres` | All data (+ pgvector) | `pg_isready` passes |
| `redis` | Task queue, locks, rate limits | `PING` → `PONG` |
| `migrate` | Applies DB migrations, then exits | **Exited (0)**, which is normal |
| `backend` | REST API | `/health/ready` returns 200 |
| `frontend` | Dashboard | `/` returns 200 |
| `job-discovery-worker` | Fetches jobs (`discovery`, `system` queues) | answers Celery ping |
| `agent-orchestrator` | Runs the full pipeline (`orchestrator` queue) | answers Celery ping |
| `matching-worker` | Reads CVs (`matching` queue) | answers Celery ping |
| `visa-worker` | Re-checks visa results (`visa` queue) | answers Celery ping |
| `application-worker` | Writes application drafts (`application` queue) | answers Celery ping |
| `scheduler` | Celery beat: starts due searches, expires old jobs | running (no health check) |

**Schedules (UTC):** every 5 minutes the scheduler checks which saved searches are due
(default search: daily 06:00). Jobs expire daily at 03:15.

---

## 2. Daily operations

### Start, stop, status

```bash
docker compose up -d            # start (or apply changes)
docker compose ps               # status and health
docker compose stop             # stop, keeping data
docker compose start            # start again after stop
```

### Health check in 30 seconds

```bash
curl -s localhost:8081/health/ready                     # {"status":"ok", ...}
curl -s -H "X-API-Key: $KEY" localhost:8081/api/v1/agents/summary | python3 -m json.tool | head -40
curl -s -X POST -H "X-API-Key: $KEY" localhost:8081/api/v1/agents/ping   # then GET /agents/tasks/<id> → SUCCESS
```

Check in `agents/summary`:
- `discovery.last_status` is `succeeded` and `last_started_at` is within the last day
- `failures_24h` is 0 for every agent

### Logs

```bash
docker compose logs -f backend                     # API requests (JSON, with request_id)
docker compose logs -f agent-orchestrator          # pipeline runs
docker compose logs --since 1h job-discovery-worker | grep -E '"level": "(warning|error)"'
```

Each API response has an `X-Request-ID` header. Search the backend log for that ID to
find the matching request.

---

## 3. Routine tasks

### Run a search now

Use **Find & analyse jobs now** on the dashboard, or:

```bash
curl -s -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  localhost:8081/api/v1/pipeline/run -d '{}'
```

### Re-score everything (after editing the profile or the reference data)

```bash
curl -s -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  localhost:8081/api/v1/pipeline/run -d '{"analyse_only": true, "force": true}'
```

Without `force`, only jobs whose inputs changed are re-analysed (no repeat LLM calls).

### Add or disable a job source

On the dashboard: **Agents → Job sources** checkbox. To add a company on Greenhouse, see
[Using the API](../wiki/Using-the-API.md#job-sources). Use only public boards and APIs.

### Back up the database

```bash
scripts/backup_db.sh                     # writes backups/eujobs-<time>.dump, keeps the newest 14
```

Schedule it daily, for example with `crontab -e`:

```
30 2 * * * cd /path/to/eu-job-intelligence && scripts/backup_db.sh >> backups/backup.log 2>&1
```

Uploaded CVs live in the `eujobs_uploads` Docker volume. To back them up too:

```bash
docker run --rm -v eujobs_uploads:/data -v "$PWD/backups":/out alpine \
  tar czf /out/uploads-$(date +%F).tgz -C /data .
```

### Restore drill (do this once, so you know it works)

```bash
scripts/restore_db.sh backups/eujobs-<time>.dump    # asks you to type "restore"
curl -s -H "X-API-Key: $KEY" localhost:8081/api/v1/stats/overview
```

### Rotate the API key

1. Add the new key next to the old one: `API_KEYS=<new>,<old>`.
2. Run `docker compose up -d backend`.
3. Paste the new key in the dashboard (**Forget API key**, then sign in again).
4. Remove the old key from `API_KEYS` and run `docker compose up -d backend` again.

### Rotate the database password

Postgres keeps the password from its first start, so changing `.env` alone breaks the
connection. Change it inside Postgres first:

```bash
docker compose exec postgres psql -U eujobs -d eujobs -c "ALTER USER eujobs PASSWORD '<new>'"
```

Then update `POSTGRES_PASSWORD` **and** the password inside `DATABASE_URL` in `.env`, and
run `docker compose up -d`.

### Upgrade to a new version

```bash
scripts/backup_db.sh
git pull
docker compose up -d --build        # migrate runs before backend and workers start
docker compose ps                   # migrate: Exited (0); everything else healthy
```

To roll back: check out the previous commit and run `docker compose up -d --build`. If
the new version changed the database schema, also restore the backup taken before the
upgrade.

### Turn on the local AI model

```bash
ollama serve &                                    # native on macOS (uses the GPU)
ollama pull llama3.2:3b && ollama pull nomic-embed-text
curl -s -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  localhost:8081/api/v1/pipeline/run -d '{"analyse_only": true, "force": true}'
```

Confirm: the `embedding` step in **Agents** shows items processed, and job details show
meaning-based similarity.

---

## 4. What to watch

| Signal | Where | Normal | Act when |
|---|---|---|---|
| Discovery ran today | Agents page / `agents/summary` | `succeeded`, < 24 h ago | older than 26 h → [5.4](#54-scheduled-searches-are-not-running) |
| Source errors | Agents → Job sources, *Last error* | empty | the same source fails 2 days running → [5.5](#55-a-job-source-keeps-failing) |
| Failed executions | `agents/executions?status=failed` | none | any → read `error_message` |
| Jobs found per run | `discovery` *Created* | some most days | 0 for a week → check keywords and countries in your search |
| API errors | `/metrics` → `eujobs_http_requests_total{status="500"}` | 0 | rising → backend logs |
| Disk | `docker system df` | stable | volumes growing fast → prune old backups and images |

---

## 5. Incident playbooks

### 5.1 Dashboard or API not reachable

1. `docker compose ps`: is `backend` or `frontend` unhealthy or restarting?
2. `docker compose logs --tail 50 backend`.
3. `curl -s localhost:8081/health/ready` shows which dependency failed:
   - `postgres` failing → [5.6](#56-database-problems)
   - `redis` failing → `docker compose restart redis`
4. If `migrate` failed, nothing else starts: `docker compose logs migrate`.
5. Port clash (`address already in use`): change `API_PORT` or `FRONTEND_PORT` in `.env`.

### 5.2 Every request returns 401

- The key in the dashboard doesn't match `API_KEYS`. Use **Forget API key** and sign in
  again with the value from `.env`.
- You edited `API_KEYS` but didn't restart: `docker compose up -d backend`.

### 5.3 Requests return 429

The per-key rate limit (`RATE_LIMIT_DEFAULT`, default 120/minute) was hit. Wait a minute,
or raise the limit in `.env` and run `docker compose up -d backend`.

### 5.4 Scheduled searches are not running

1. `docker compose ps scheduler` → must be running. Then
   `docker compose logs --since 30m scheduler | grep dispatch` → should show
   `Sending due task discovery-dispatch-due` every 5 minutes.
2. Check the search is enabled and its cron line is valid:
   `GET /api/v1/candidate/search-configs` (`enabled: true`, e.g. `0 6 * * *`).
3. Is a previous run still holding the lock? A run that crashed holds it for up to 2 hours.
   ```bash
   docker compose exec redis sh -c 'redis-cli -a "$REDIS_PASSWORD" --no-auth-warning keys "lock:*"'
   ```
   Clear a stale lock (only if no run is in progress):
   ```bash
   docker compose exec redis sh -c 'redis-cli -a "$REDIS_PASSWORD" --no-auth-warning del lock:pipeline:<search-config-id>'
   ```
4. `docker compose restart scheduler agent-orchestrator`.

### 5.5 A job source keeps failing

Read *Last error* on **Agents → Job sources**:

| Error contains | Meaning | Fix |
|---|---|---|
| `HTTP 404` | Company moved off that board, or a wrong token | Disable the source, or fix `board_token`/`site` |
| `robots.txt` | The site now disallows fetching | Disable the source. Never work around it |
| `HTTP 429` / `5xx` after retries | Rate-limited or the site is down | Usually clears by itself. Lower `rate_limit_per_minute` for that source |
| `AdzunaNotConfigured` | Adzuna enabled without keys | Set `ADZUNA_APP_ID`/`ADZUNA_APP_KEY`, or disable the source |

One failing source never stops the others.

### 5.6 Database problems

- **Postgres won't start after changing `.env`**: the password changed. See
  [Rotate the database password](#rotate-the-database-password), or put the old one back.
- **Disk full**: `docker system df`, then remove old dumps in `backups/` and unused images
  (`docker image prune`).
- **Data looks wrong after an upgrade**: stop the stack, restore the last backup
  ([Restore drill](#restore-drill-do-this-once-so-you-know-it-works)), then check out the
  previous version.

### 5.7 A worker is unhealthy or tasks are stuck

```bash
docker compose ps                                   # which worker?
docker compose logs --tail 80 <worker>
docker compose exec backend celery -A workers.celery_app inspect active    # what is running
docker compose restart <worker>
```

Tasks are acknowledged only after they finish (`acks_late`), so a task interrupted by a
restart is delivered again. Out-of-memory kills show up as `Exited (137)`: raise that
service's `memory` limit in `docker-compose.yml`.

### 5.8 AI features off ("AI model not running")

This is expected when Ollama isn't running. Everything still works with rule-based
scoring. To turn the AI on, see [Turn on the local AI model](#turn-on-the-local-ai-model).

If Ollama **is** running:
- `curl -s localhost:11434/api/tags` lists both models
- `OLLAMA_BASE_URL` in `.env` is `http://host.docker.internal:11434`
- `LLM_CHAT_MODEL` and `LLM_EMBEDDING_MODEL` match the pulled names

### 5.9 A resume shows "could not read"

It's probably a scanned (image-only) PDF; OCR isn't supported. Upload a DOCX or a
text-based PDF. To retry parsing: **Profile → Resumes → Analysis → Try again**.

### 5.10 Scores look wrong

1. Open the job and read **Why this score**: the reasons list every component.
2. Common causes:
   - work authorization, minimum salary or skill levels not set in **Profile**
   - match weights changed
   - no AI model, so no meaning-based matching
3. After fixing the profile, [re-score everything](#re-score-everything-after-editing-the-profile-or-the-reference-data).
4. Salary reference numbers are approximate: edit `data/salary_reference.json`, rebuild
   (`docker compose up -d --build`), then re-score.

---

## 6. Safety rules (never change these)

- The system **never** applies to jobs or sends messages. Drafts need your approval, and
  you send them yourself.
- Never assume citizenship or work authorization. Unknown stays unknown.
- Only public APIs and feeds. Respect robots.txt and rate limits. No logins, no CAPTCHA
  workarounds.
- Visa conclusions need quoted evidence. International staff is not evidence of
  sponsorship.
- Never commit `.env` or backups. `.gitignore` already excludes them.

---

## 7. Kubernetes (k3d)

Every command names the cluster's context, so your other clusters are never touched.

```bash
alias kk='kubectl --context k3d-eujobs -n eujobs'
```

### Start, stop, status

```bash
scripts/k8s-up.sh                 # create the cluster and install, or upgrade after changes
k3d cluster stop eujobs           # pause (keeps data)
k3d cluster start eujobs          # resume
kk get pods,pvc,hpa,ingress       # status
helm test eujobs --kube-context k3d-eujobs -n eujobs   # in-cluster smoke test
scripts/k8s-up.sh --delete        # delete the cluster and all its data
```

Dashboard: http://eujobs.localhost:8088. API key:

```bash
kk get secret eujobs-secrets -o jsonpath='{.data.API_KEYS}' | base64 -d; echo
```

> On a machine with little memory, stop one stack before starting the other
> (`docker compose stop` / `k3d cluster stop eujobs`).

### Scaling

The backend and the discovery and matching workers have autoscalers. **`kubectl scale`
is overridden by an autoscaler**, so change its limits instead:

```bash
kk patch hpa eujobs-matching-worker -p '{"spec":{"minReplicas":3}}'
kk get hpa
```

Workers without an autoscaler (orchestrator, visa, application) can be scaled directly:
`kk scale deploy/eujobs-visa-worker --replicas=2`. Never scale `eujobs-scheduler` above 1.

### Pod playbooks

| Symptom (`kk get pods`) | Meaning | Check / fix |
|---|---|---|
| `Init:0/1` for minutes | Waiting for the DB or migrations | `kk logs <pod> -c wait-for-db`, then `kk get pods -l app.kubernetes.io/component=migrate` |
| Migrate job `Error`/`BackOff` | Migration failed | `kk logs job/eujobs-migrate-<revision>` |
| `CrashLoopBackOff` | App fails at start | `kk logs <pod> --previous` |
| `OOMKilled` | Memory limit too low | Raise `resources.limits.memory` in `values.yaml` and re-run `scripts/k8s-up.sh` |
| `Pending` | No room on the node, or PVC not bound | `kk describe pod <pod>`; free memory, or check `kk get pvc` |
| HPA `cpu: <unknown>` | metrics-server still starting | Wait 1–2 minutes |

After deleting pods, `rollout status` can report success before the replacements are
ready. Wait for readiness explicitly:

```bash
kk wait --for=condition=ready pod -l app.kubernetes.io/component=backend --timeout=240s
```

### Upgrade and roll back

```bash
scripts/k8s-up.sh                                              # builds, imports, upgrades
helm history eujobs --kube-context k3d-eujobs -n eujobs
helm rollback eujobs <revision> --kube-context k3d-eujobs -n eujobs
```

Each revision runs its own migrate Job. Rolling back the chart does **not** roll back the
database schema: restore a backup if needed.

### Back up the database on Kubernetes

```bash
kk exec eujobs-postgres-0 -- sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > backups/k8s-$(date +%F).dump
```

### What was tested

On a one-node k3d cluster, all of the following was verified:
- **Install:** all pods ready, the migration Job completed, and `helm test` passed.
- **End-to-end run** through the ingress: 13 jobs discovered and analysed.
- **Autoscaling:** the autoscalers scaled the backend to 2 and discovery to 3 under load.
- **Manual scaling:** 3 matching workers each registered separately with Celery.
- **Persistence:** deleting the Postgres and Redis pods kept all data.
- **Self-healing:** deleted backend pods were replaced and became ready.
- **Shared storage:** the uploads volume is shared across pods.
