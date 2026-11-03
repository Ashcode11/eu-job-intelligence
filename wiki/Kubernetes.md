# Running on Kubernetes

Docker Compose is the easiest way to run the platform. Kubernetes is optional, for
practising a real deployment: independent scaling, self-healing and persistent storage.

## What you need

- Docker Desktop with **at least 4 GB** of memory
- [k3d](https://k3d.io): `brew install k3d`
- Helm 3 and kubectl: `brew install helm kubectl`

> Stop the Compose stack first (`docker compose stop`) on a small machine. Running both
> needs about twice the memory. Your Compose data stays in its Docker volumes.

## One command

```bash
scripts/k8s-up.sh
```

It creates a one-node k3d cluster called `eujobs`, builds and loads the images, installs
the Helm chart, and waits until everything is ready. It **does not change your current
kubectl context**: every command names `k3d-eujobs` explicitly.

Open **http://eujobs.localhost:8088** and paste your API key:

```bash
kubectl --context k3d-eujobs -n eujobs get secret eujobs-secrets -o jsonpath='{.data.API_KEYS}' | base64 -d; echo
```

Load the sample profile and job sources (once):

```bash
kubectl --context k3d-eujobs -n eujobs exec deploy/eujobs-backend -- python -m scripts.seed --no-jobs
```

Check it from inside the cluster:

```bash
helm test eujobs --kube-context k3d-eujobs -n eujobs
```

## What gets deployed

| Kind | Name | Notes |
|---|---|---|
| StatefulSet + PVC | postgres | pgvector, 5 Gi volume |
| StatefulSet + PVC | redis | append-only file on a 1 Gi volume |
| Job | migrate | runs `alembic upgrade head` on every install or upgrade |
| Deployment | backend | readiness `/health/ready`, liveness `/health/live`, autoscaled 1–3 |
| Deployment ×5 | discovery, orchestrator, matching, visa, application workers | one per queue; discovery and matching autoscale 1–4 |
| Deployment | scheduler | Celery beat, always exactly 1 |
| Deployment | frontend | the dashboard |
| Ingress | eujobs.localhost | dashboard at `/`, API at `/api`, `/docs`, `/health` |
| Secret | eujobs-secrets | random passwords and API key, kept across upgrades |
| ConfigMap | eujobs-config | non-secret settings |
| PVC | uploads | uploaded and tailored CVs; kept on `helm uninstall` |

Every app pod waits (initContainer) until the database is reachable **and** fully
migrated, so nothing starts against an old schema.

## Scaling

```bash
# by hand
kubectl --context k3d-eujobs -n eujobs scale deploy/eujobs-matching-worker --replicas=3
# autoscaler status
kubectl --context k3d-eujobs -n eujobs get hpa
```

Change defaults in `values.yaml` under `workers.<name>` (replicas, concurrency, resources,
autoscaling).

## The AI model on Kubernetes

By default the pods use Ollama on your Mac (`http://host.k3d.internal:11434`). To run
it inside the cluster, set `ollama.enabled=true`. It needs about 3 GB of RAM for a 3B
model.

**GPUs are not automatic.** Kubernetes only schedules GPUs after the NVIDIA device plugin
is installed on a node with an NVIDIA GPU. Then set `ollama.gpu.enabled=true`, plus
`nodeSelector`/`tolerations` if needed. Docker on macOS cannot pass the Apple GPU into
containers at all.

## Your own settings

```bash
scripts/k8s-up.sh --set secrets.adzunaAppId=... --set secrets.adzunaAppKey=...
```

Or keep your own Secret and set `secrets.existingSecret=<name>`. It needs the keys
`POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `API_KEYS`, `DATABASE_URL` and `REDIS_URL`.

## Plain manifests

`infrastructure/kubernetes/manifests/eujobs.yaml` is the rendered chart for
`kubectl apply` users. Replace the `CHANGE_ME` values first.

## Remove it

```bash
scripts/k8s-up.sh --delete
```

This deletes the cluster and everything in it. Your Docker Compose data is separate and
untouched. Restart it with `docker compose start`.
