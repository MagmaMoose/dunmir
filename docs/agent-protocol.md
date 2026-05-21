# Agent protocol

The Mikrotik Minder control plane is a public HTTPS service. Agents run on a trusted host inside the operator's network, talk to routers over SSH / RouterOS API, and POST the *outcomes* (heartbeats and job reports) to this service. The service stores them and fires outbound webhook alerts when expected events are missing.

The protocol is intentionally small: an agent only needs an HTTP client.

The OSS worker exposes ingest + admin REST endpoints and a public health probe; the operator-facing UI (config browser, backup vault, etc.) is a separate, licensed product.

## Authentication

All non-public endpoints require `Authorization: Bearer <token>`.

| Token         | Used for                                       |
| ------------- | ---------------------------------------------- |
| `ADMIN_TOKEN` | Admin REST API (mint/manage agent tokens etc.) |
| Agent token   | `/v1/ingest/*` (issued by the admin per-agent) |

`GET /` and `GET /v1/health` are unauthenticated and return small JSON identifying the service.

Agent tokens are returned exactly once by `POST /v1/admin/agents`. Re-issue with `POST /v1/admin/agents/:id/rotate-token`. The server stores a SHA-256 hash, never the token itself.

## Endpoints

### `POST /v1/ingest/heartbeat`

Agents send a heartbeat per managed device on whatever interval was configured. The first heartbeat for a previously-unknown device auto-registers it under the calling agent.

```json
{ "device": "core-rtr-01", "status": "ok" }
```

- `device` (required) — the device name (or its `dev_*` id).
- `status` (optional, default `ok`) — `ok` | `degraded` | `down` | `unknown`.

A heartbeat that transitions a device from `down` back to anything else emits a `heartbeat_recovered` info alert.

### `POST /v1/ingest/jobs`

Agents send one record per completed maintenance job.

```json
{
  "device": "core-rtr-01",
  "kind": "backup",
  "status": "success",
  "started_at": 1779218770,
  "finished_at": 1779218782,
  "summary": "encrypted backup pulled (12s)",
  "details": { "size_bytes": 18432, "git_commit": null }
}
```

- `kind` — one of `backup`, `export`, `drift`, `update_check`, `update_apply`, `firmware_align`, `health_check`, `restore_validate`, `inventory_sync`.
- `status` — `success` | `warning` | `failed` | `skipped`.
- `started_at` / `finished_at` — unix seconds.
- `summary` — short human-readable line (≤ 500 chars); surfaces in outbound alerts and is the human-readable record stored alongside the job.
- `details` — arbitrary JSON; stored verbatim.
- `device` — optional for fleet-wide jobs (e.g. `update_check --all`).

Automatic alert mapping:

| Job kind                          | Job status | Alert kind        | Severity   |
| --------------------------------- | ---------- | ----------------- | ---------- |
| `update_apply` / `firmware_align` | `failed`   | `update_failed`   | critical   |
| any other kind                    | `failed`   | `job_failed`      | warning    |
| `drift`                           | `warning`  | `drift_detected`  | warning    |

### `kind=export` and `kind=drift` payload shape

The Python agent ships these `details` fields for export-pipeline jobs:

```json
{
  "bytes_captured": 18432,
  "changed": true,
  "commit_sha": "0744a01...",
  "lines_added": 1,
  "lines_removed": 0,
  "relative_path": "devices/core-rtr-01/exports/latest.rsc",
  "pushed": true,
  "push_skipped": false,
  "push_error": null
}
```

Status mapping:

| Commit       | Push                  | Result                          | Worker alert      |
| ------------ | --------------------- | ------------------------------- | ----------------- |
| no change    | n/a (skipped)         | `kind=export, status=success`   | none              |
| changed      | ok or skipped         | `kind=drift, status=warning`    | `drift_detected`  |
| no change    | failed                | `kind=export, status=failed`    | `job_failed`      |
| changed      | failed                | `kind=drift, status=failed`     | `job_failed`      |
| capture err  | n/a                   | `kind=export, status=failed`    | `job_failed`      |

`push_skipped=true` is the normal state when no `git.remote` is configured or `git.remote.push=false`. `push_error` is null when the push wasn't attempted or it succeeded.

Changes that only affect the volatile `# <timestamp> by RouterOS …` header are filtered out locally; they never reach the worker.

### `kind=update_check` and `kind=firmware_align` payload shape

`update_check` posted with `status=success` when up-to-date and `status=warning` when an update is available:

```json
{
  "channel": "stable",
  "installed_version": "7.18.2",
  "latest_version": "7.22.3",
  "status": "New version is available",
  "available": true
}
```

`firmware_align` is only posted when the device has routerboard firmware to align (CHRs and similar virtual routers skip it):

```json
{
  "model": "RB5009UPr+S+",
  "current_firmware": "7.17.2",
  "upgrade_firmware": "7.18.2",
  "mismatch": true
}
```

When `status=warning` for either kind the worker fires a single `update_available` alert (warning severity).

### `kind=backup` payload shape

```json
{
  "file_name": "minder-core-rtr-01-20260520T184419Z.backup",
  "file_path": "/var/lib/mikrotik-minder/backups/core-rtr-01/minder-...backup",
  "size_bytes": 28613,
  "sha256": "15f8cfadb360...",
  "retained": 14,
  "pruned": 1
}
```

Always `status=success` on a clean run; on failure the agent emits `status=failed` and the worker fires `job_failed`.

### `kind=update_apply` payload shape

This is only emitted by the explicit `mikrotik-minder-agent update apply DEVICE --approve TICKET` command, never by the daemon. Two failure modes are distinguished by `aborted_pre_install`:

```json
{
  "ticket": "CHG-1234",
  "before_version": "7.18.2 (stable)",
  "after_version": "7.22.3 (stable)",
  "downtime_seconds": 96,
  "before_free": "46.2GiB",
  "after_free": "45.7GiB"
}
```

- `status=success`: install completed; before/after versions captured.
- `status=failed`, `aborted_pre_install=true`: pre-check stopped us before issuing the install. Router untouched.
- `status=failed`, `aborted_pre_install=false`: install was issued but the router did not return cleanly. Worker fires a critical `update_failed` alert.

## Cron sweep

Every minute the worker scans devices with `last_seen_at + interval + grace < now` and `last_status != 'down'`. For each, it sets the device to `down` and emits a `heartbeat_missed` critical alert with `last_seen_seconds_ago` in the payload. This is the dead-man feature called out in the product README under *Watchdog heartbeat / dead-man alert*.

Default interval and grace come from `wrangler.toml` (`DEFAULT_HEARTBEAT_INTERVAL_SECONDS`, `DEFAULT_GRACE_SECONDS`) and can be overridden per device.

## Admin REST API

All under `/v1/admin`, gated by `ADMIN_TOKEN`. Examples in [`./examples.http`](./examples.http).

| Method | Path                                | Purpose                                                    |
| ------ | ----------------------------------- | ---------------------------------------------------------- |
| POST   | `/v1/admin/agents`                  | Create agent; returns the bearer token *once*.             |
| GET    | `/v1/admin/agents`                  | List agents.                                               |
| POST   | `/v1/admin/agents/:id/disable`      | Disable an agent token without deleting history.           |
| POST   | `/v1/admin/agents/:id/rotate-token` | Rotate the bearer token.                                   |
| POST   | `/v1/admin/devices`                 | Upsert a device (sets site / role / tags / interval / grace). |
| GET    | `/v1/admin/devices`                 | List devices with last-seen state.                         |
| DELETE | `/v1/admin/devices/:id`             | Remove a device.                                           |
| POST   | `/v1/admin/alert-routes`            | Register a Slack / Discord / generic webhook sink.         |
| GET    | `/v1/admin/alert-routes`            | List sinks.                                                |
| DELETE | `/v1/admin/alert-routes/:id`        | Remove a sink.                                             |
| POST   | `/v1/admin/alerts/test`             | Fire an `info` / `manual` alert across all matching sinks. |

Public (no auth):

- `GET /` — service identifier JSON.
- `GET /v1/health` — liveness probe.

Read-only fleet/job/alert browsing is intentionally NOT in the OSS worker — that's what the licensed Pages frontend is for. Self-hosters who want a quick read-only API can query D1 directly with `wrangler d1 execute`.

## Alert routes

A route stores `kind` (`webhook` | `slack` | `discord`), `url`, `events` (optional allowlist of alert kinds), and `min_severity` (`info` | `warning` | `critical`).

- **Slack**: posted as the legacy `{text, attachments[]}` shape so an Incoming Webhook URL Just Works.
- **Discord**: posted as `{username, embeds[]}` for inline display.
- **Webhook**: the raw alert envelope (`{id, severity, kind, title, agent_id, device_id, job_id, payload, created_at}`) for routing into your own pipeline.

Every delivery attempt is recorded in `alert_deliveries` with the HTTP status and any error.

## Quickstart curls

```bash
ADMIN=...                       # from `wrangler secret put ADMIN_TOKEN`
BASE=https://mikrotik-minder.<your-subdomain>.workers.dev

# 1. create an agent and capture its token
AGENT=$(curl -sS -X POST "$BASE/v1/admin/agents" \
  -H "authorization: bearer $ADMIN" -H "content-type: application/json" \
  -d '{"name":"homelab-agent"}')
TOKEN=$(echo "$AGENT" | jq -r .token)

# 2. (optional) pre-declare a device with overrides
curl -sS -X POST "$BASE/v1/admin/devices" \
  -H "authorization: bearer $ADMIN" -H "content-type: application/json" \
  -d "{\"agent_id\":\"$(echo $AGENT | jq -r .id)\",\"name\":\"core-rtr-01\",\"site\":\"dc1\",\"role\":\"core\",\"heartbeat_interval_seconds\":900}"

# 3. add a Slack sink
curl -sS -X POST "$BASE/v1/admin/alert-routes" \
  -H "authorization: bearer $ADMIN" -H "content-type: application/json" \
  -d '{"name":"ops-slack","kind":"slack","url":"https://hooks.slack.com/services/...","min_severity":"warning"}'

# 4. send a heartbeat from the agent
curl -sS -X POST "$BASE/v1/ingest/heartbeat" \
  -H "authorization: bearer $TOKEN" -H "content-type: application/json" \
  -d '{"device":"core-rtr-01","status":"ok"}'

# 5. record a job
NOW=$(date +%s)
curl -sS -X POST "$BASE/v1/ingest/jobs" \
  -H "authorization: bearer $TOKEN" -H "content-type: application/json" \
  -d "{\"device\":\"core-rtr-01\",\"kind\":\"backup\",\"status\":\"success\",\"started_at\":$((NOW-12)),\"finished_at\":$NOW,\"summary\":\"backup ok\"}"
```
