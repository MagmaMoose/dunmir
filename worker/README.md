# Mikrotik Minder — control plane (worker)

FastAPI on a **Cloudflare Python Worker**, backed by **D1** (SQLite) and **R2**
(encrypted backup bodies). This is the hosted control plane: heartbeat / job
ingest, the dead-man-alert cron, command dispatch, encrypted-backup catalog, and
the operator admin API. It holds no router credentials — agents report in, and
credentials are only ever stored as references or opaque sealed blobs.

## Layout

```
src/
  entry.py        # Cloudflare WorkerEntrypoint: ASGI fetch + cron `scheduled`
  app.py          # FastAPI app (routers, error handlers, landing + health)
  routes/
    ingest.py     # /v1/ingest/*   — agent-authenticated (mtm_ tokens)
    admin.py      # /v1/admin/*    — operator (Stytch session or admin token)
    tenants.py    # /v1/superadmin/tenants/* — cross-tenant superadmin
  auth.py         # token hashing, bearer extraction, auth dependencies
  stytch.py       # Stytch B2B session-JWT validation + JIT tenant onboarding
  notify.py       # alert persistence + Slack/Discord/webhook fan-out
  scheduled.py    # dead-man sweep (cron)
  d1.py / r2.py / outbound.py  # thin async wrappers over the Workers bindings
  env.py / deps.py / schema.py / ids.py / bodies.py / errors.py
migrations/       # D1 schema (unchanged; shared with the Pro app's chain)
tests/            # pytest suite over an in-memory SQLite shim of the D1 surface
```

The route handlers talk to a small async DB interface
(`prepare(sql).bind(...).first()/all()/run()` + `batch()`). In production that's
`d1.D1Database` over the Workers `env.DB` binding; in tests it's
`tests/d1_shim.py` over in-memory SQLite — so the real app, routers, auth, and SQL
are exercised in CI without the Workers runtime. The only deferred-to-runtime
pieces are the Web Crypto JWT verify (`stytch._verify_rs256`/`_load_jwks`) and
`outbound.fetch`, which the tests substitute.

## Develop

```bash
pip install -r requirements.txt
pip install pytest httpx cryptography   # test-only deps
pytest -q                               # tenant isolation + customer auth + git-remote
python -m compileall -q src             # quick syntax check

# Run on the Workers runtime locally (needs Node + wrangler):
npx wrangler@4 dev
```

## Deploy

CI (`.github/workflows/worker-deploy.yml`) applies D1 migrations and deploys to the
`prod` environment via `wrangler deploy --env prod`. Self-hosters: set the
`CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` secrets, point `wrangler.toml` at
your own D1 (`database_id`) and R2 bucket, then `wrangler secret put ADMIN_TOKEN`.

Bindings, vars, and secrets are unchanged from the previous TypeScript worker — see
`wrangler.toml` for the full list (`DB`, `BACKUPS`, `ADMIN_TOKEN`, `SLACK_BOT_TOKEN`,
the `STYTCH_*` vars, etc.). The wire contract is unchanged: see
[`docs/agent-protocol.md`](../docs/agent-protocol.md).
