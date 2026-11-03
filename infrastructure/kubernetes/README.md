# Kubernetes

Two ways to deploy:

1. **Helm (recommended)**: `infrastructure/helm/eu-job-intelligence`. Use
   `scripts/k8s-up.sh` for a local k3d cluster.
2. **Plain manifests**: `manifests/eujobs.yaml` is `helm template` output with default
   values. It's for `kubectl apply` users and for review. Edit the Secret before applying:
   the rendered file contains placeholder passwords.

Regenerate the manifests after changing the chart:

```bash
helm template eujobs infrastructure/helm/eu-job-intelligence --namespace eujobs \
  --set secrets.postgresPassword=CHANGE_ME --set secrets.redisPassword=CHANGE_ME \
  --set secrets.apiKeys=CHANGE_ME > infrastructure/kubernetes/manifests/eujobs.yaml
```

`k3d-cluster.yaml` defines the local cluster: one node, with the ingress on
`127.0.0.1:8088`.
