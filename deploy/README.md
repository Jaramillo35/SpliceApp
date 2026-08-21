# Deploying splice-api to local Kubernetes (Phase 4)

Runs the containerized API on a real Kubernetes cluster locally via **kind** (Kubernetes IN
Docker) + **Helm**. The chart is cloud-portable — the same `helm install` targets AKS/EKS by
pointing at a registry image instead of a kind-loaded one.

## Prerequisites

```bash
brew install kind helm kubectl     # one-time
```

Docker Desktop (or Colima) must be running — kind runs the cluster inside Docker.

## Bring-up

```bash
# 0. Build the image (if not already built)
cd apps/Splice
docker build -f splice_api/Dockerfile -t splice-api:local .

# 1. Create a local cluster
kind create cluster --config deploy/kind/kind-cluster.yaml

# 2. Load the local image into the cluster (no registry needed)
kind load docker-image splice-api:local --name harness

# 3. Install the chart (lint/preview first if you like)
helm lint deploy/helm/splice-api
helm install splice-api deploy/helm/splice-api

# 4. Wait for the rollout, then port-forward and hit it
kubectl rollout status deploy/splice-api
kubectl port-forward svc/splice-api 8000:80
#   → in another terminal:
#     curl http://localhost:8000/health
#     open  http://localhost:8000/docs
```

## Teardown

```bash
helm uninstall splice-api
kind delete cluster --name harness
```

## What the chart provisions

- **Deployment** — non-root (uid 10001), read-only root FS + a writable `/tmp` emptyDir (the
  `/preorder` endpoint uses tempfiles), dropped capabilities, `RuntimeDefault` seccomp.
- **liveness/readiness probes** on `/health` — Kubernetes restarts a wedged pod and keeps
  traffic off one that isn't ready.
- **Service** (ClusterIP) — stable in-cluster address; port 80 → container port 8000.
- **ServiceAccount** and an optional **Ingress** (disabled by default; enable with
  `--set ingress.enabled=true`).
