# Mikrotik Minder — control plane (backend)

A single **FastAPI** codebase that runs on two backends:

- **Cloudflare Python Worker + D1 + R2** — the **first-class** hosted target.
- **Postgres + filesystem (or object) storage** — the **portable** target, served by
  uvicorn in Docker, Kubernetes, or locally.

It's the hosted control plane: heartbeat / job ingest, the dead-man-alert sweep,
command dispatch, encrypted-backup catalog, and the operator admin API. It holds no
router credentials — agents report in, and credentials are only ever stored as
references or opaque sealed blobs.

## How portability works

The route handlers talk to one small async DB interface
(`prepare(sql).bind(...).first()/all()/run()` + `batch()`) and one storage
interface (`get`/`put`/`delete`). The runtime is selected at the edges:

| Concern        | Cloudflare (first-class)        | Portable (Docker / k8s / local) |
| -------------- | ------------------------------- | ------------------------------- |
| Database       | `d1.D1Database` (D1)            | `pg.PgDatabase` (asyncpg)       |
| Object storage | `r2.R2Bucket` (R2)             | `storage_fs.FilesystemStorage`  |
| Outbound HTTP  | runtime `fetch`                 | `httpx`                         |
| JWT verify     | Web Crypto                      | `cryptography`                  |
| Entry          | `entry.py` (WorkerEntrypoint)   | `server.py` (uvicorn) + `app.py` lifespan |
| Cron sweep     | cron trigger → `scheduled`      | `sweep.py` (k8s CronJob)        |

Handler SQL is written once in the D1/SQLite dialect; the Postgres adapter rewrites
it on the way to the driver (`?N`→`$N`, `INSERT OR IGNORE`→`ON CONFLICT DO NOTHING`).
The DB is chosen by `DATABASE_URL`: set it → Postgres (app lifespan builds
`env.StandaloneEnv`); unset, on Cloudflare → the D1 binding from the request scope.

## Layout

```
src/
  entry.py        # Cloudflare WorkerEntrypoint: ASGI fetch + cron `scheduled`
  server.py       # uvicorn entry for the portable deployment
  app.py          # FastAPI app (routers, error handlers, landing + health, lifespan)
  routes/         # ingest (agent) · admin (operator) · tenants (superadmin)
  auth.py         # token hashing, bearer extraction, auth dependencies
  stytch.py       # Stytch B2B session-JWT validation + JIT tenant onboarding
  notify.py       # alert persistence + Slack/Discord/webhook fan-out
  scheduled.py    # dead-man sweep ;  sweep.py — one-shot sweep entry (k8s CronJob)
  d1.py / r2.py            # Cloudflare adapters
  pg.py / storage_fs.py    # portable (Postgres / filesystem) adapters
  migrate.py      # apply migrations to Postgres (idempotent)
  outbound.py / env.py / deps.py / schema.py / ids.py / bodies.py / errors.py
migrations/       # schema (D1 dialect; translated to PG by migrate.py)
tests/            # pytest: real app over a SQLite shim + a gated PG integration suite
```

## Develop & test

```bash
pip install -r requirements.txt -r requirements-standalone.txt
pip install pytest pytest-asyncio
pytest -q                       # tenant isolation, customer auth, git-remote, PG dialect
python -m compileall -q src     # quick syntax check

# Optional: run the gated Postgres integration suite against a throwaway DB
DATABASE_URL=postgresql://user:pass@localhost:5432/minder pytest -q tests/test_pg_integration.py
```

## Run

```bash
# Cloudflare (needs Node + wrangler):
npx wrangler@4 dev

# Portable (Postgres), locally:
export DATABASE_URL=postgresql://minder:minder@localhost:5432/minder
export ADMIN_TOKEN=dev-admin-token
python -m migrate          # apply schema (idempotent)
python -m server           # uvicorn on :8000  (or: uvicorn app:app --port 8000)
```

For containers/k8s see the repo-root [`docker-compose.yml`](../docker-compose.yml)
and [`deploy/k8s/`](../deploy/k8s/). The `Dockerfile` here builds the portable image
(migrations on boot, then uvicorn).

## Deploy (Cloudflare, first-class)

CI (`.github/workflows/worker-deploy.yml`) applies D1 migrations and deploys to the
`prod` environment via `wrangler deploy --env prod`. Self-hosters: set the
`CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` secrets, point `wrangler.toml` at
your own D1 (`database_id`) and R2 bucket, then `wrangler secret put ADMIN_TOKEN`.

Bindings, vars, and secrets (`DB`, `BACKUPS`, `ADMIN_TOKEN`, `SLACK_BOT_TOKEN`, the
`STYTCH_*` vars, …) are in `wrangler.toml`. The wire contract is unchanged: see
[`docs/agent-protocol.md`](../docs/agent-protocol.md).
