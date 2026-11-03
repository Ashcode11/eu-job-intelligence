#!/usr/bin/env bash
# Create a local k3d cluster, load the images and install the Helm chart.
#   scripts/k8s-up.sh            # create/upgrade
#   scripts/k8s-up.sh --delete   # remove the cluster (all its data)
# Every kubectl/helm call names the k3d context explicitly.
set -euo pipefail
cd "$(dirname "$0")/.."
CLUSTER=eujobs
CTX="k3d-$CLUSTER"
NS=eujobs
TAG="${IMAGE_TAG:-dev}"

if [ "${1:-}" = "--delete" ]; then
  k3d cluster delete "$CLUSTER"
  exit 0
fi

command -v k3d >/dev/null || { echo "Install k3d first: brew install k3d"; exit 1; }
command -v helm >/dev/null || { echo "Install Helm first: brew install helm"; exit 1; }

if ! k3d cluster list "$CLUSTER" >/dev/null 2>&1; then
  k3d cluster create --config infrastructure/kubernetes/k3d-cluster.yaml
fi

echo "==> Building images"
docker compose build backend frontend

echo "==> Importing images into the cluster"
k3d image import -c "$CLUSTER" "eujobs/python:$TAG" "eujobs/frontend:$TAG"

echo "==> Installing chart"
helm upgrade --install eujobs infrastructure/helm/eu-job-intelligence \
  --kube-context "$CTX" --namespace "$NS" --create-namespace \
  --set image.python.tag="$TAG" --set image.frontend.tag="$TAG" "$@"

echo "==> Waiting for pods"
kubectl --context "$CTX" -n "$NS" wait --for=condition=complete "job/eujobs-migrate-$(helm --kube-context "$CTX" -n "$NS" status eujobs -o json | python3 -c 'import json,sys;print(json.load(sys.stdin)["version"])')" --timeout=300s
kubectl --context "$CTX" -n "$NS" rollout status deploy --timeout=300s

echo
echo "Dashboard: http://eujobs.localhost:8088"
echo "API key:   kubectl --context $CTX -n $NS get secret eujobs-secrets -o jsonpath='{.data.API_KEYS}' | base64 -d; echo"
