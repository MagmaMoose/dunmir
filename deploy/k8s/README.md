# Kubernetes deployment (portable path)

Demo manifests for running the control plane on Kubernetes. **Cloudflare (D1 +
Pages) is the first-class hosting target**; this is the portable alternative that
runs the same FastAPI app against Postgres, alongside the React frontend.

## Build the images

```bash
docker build -t mikrotik-minder-backend:latest ./worker
docker build -t mikrotik-minder-frontend:latest ./frontend
# For a local cluster, load them in (no registry needed):
#   kind load docker-image mikrotik-minder-backend:latest mikrotik-minder-frontend:latest
#   minikube image load mikrotik-minder-backend:latest mikrotik-minder-frontend:latest
```

## Apply

```bash
kubectl apply -k deploy/k8s
# or: kubectl apply -f deploy/k8s
```

This creates the `minder` namespace, a demo Postgres `StatefulSet`, a one-shot
migration `Job`, the backend `Deployment` + `Service`, a `CronJob` running the
dead-man sweep every minute (the Cloudflare-cron equivalent), and the frontend
`Deployment` + `Service` + optional `Ingress`.

## Before real use

- Edit the `minder-backend` `Secret` (`ADMIN_TOKEN`, `DATABASE_URL`, `POSTGRES_PASSWORD`).
- Prefer a managed Postgres over the demo `StatefulSet` — just repoint `DATABASE_URL`.
- Set the frontend `API_BASE` (and the `Ingress` host) to your real backend URL.
- Backend backups use a `ReadWriteOnce` PVC (single replica). To scale the backend,
  use a `ReadWriteMany` volume or switch backup storage to S3/R2.
