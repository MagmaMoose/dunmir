import { Hono } from "hono";
import type { AppContext } from "../env";
import { generateAgentToken, hashToken, requireAdmin } from "../auth";
import { newId, nowSeconds } from "../ids";
import {
  ALERT_KINDS,
  asEnum,
  asInt,
  asOptionalBool,
  asOptionalEnum,
  asOptionalInt,
  asOptionalString,
  asString,
  asStringArray,
  COMMAND_KINDS,
  ROUTE_KINDS,
  SEVERITIES,
  TRANSPORTS,
  type AlertKind,
  type Severity,
} from "../schema";
import { fireAlert } from "../notify";

const admin = new Hono<AppContext>();
admin.use("*", requireAdmin());

// --- Agents ---------------------------------------------------------------

admin.post("/agents", async (c) => {
  const body = await c.req.json().catch(() => null);
  const name = asString(body?.name, "name", { max: 100 });
  if (!name.ok) return c.json({ error: name.error }, 400);

  const token = generateAgentToken();
  const tokenHash = await hashToken(token);
  const id = newId("agent");
  const now = nowSeconds();
  try {
    await c.env.DB.prepare(
      "INSERT INTO agents (id, name, token_hash, created_at) VALUES (?1, ?2, ?3, ?4)",
    )
      .bind(id, name.value, tokenHash, now)
      .run();
  } catch (err) {
    if (String(err).includes("UNIQUE")) return c.json({ error: "agent name already exists" }, 409);
    throw err;
  }
  return c.json({ id, name: name.value, token, created_at: now }, 201);
});

admin.get("/agents", async (c) => {
  const { results } = await c.env.DB.prepare(
    "SELECT id, name, created_at, last_seen_at, disabled FROM agents ORDER BY created_at DESC",
  ).all();
  return c.json({ agents: results });
});

admin.post("/agents/:id/disable", async (c) => {
  const id = c.req.param("id");
  const res = await c.env.DB.prepare("UPDATE agents SET disabled = 1 WHERE id = ?1").bind(id).run();
  if ((res.meta.changes ?? 0) === 0) return c.json({ error: "not found" }, 404);
  return c.json({ ok: true });
});

admin.post("/agents/:id/rotate-token", async (c) => {
  const id = c.req.param("id");
  const token = generateAgentToken();
  const tokenHash = await hashToken(token);
  const res = await c.env.DB.prepare("UPDATE agents SET token_hash = ?1, disabled = 0 WHERE id = ?2")
    .bind(tokenHash, id)
    .run();
  if ((res.meta.changes ?? 0) === 0) return c.json({ error: "not found" }, 404);
  return c.json({ id, token });
});

// --- Devices --------------------------------------------------------------

admin.post("/devices", async (c) => {
  const body = await c.req.json().catch(() => null);
  const agentId = asString(body?.agent_id, "agent_id");
  if (!agentId.ok) return c.json({ error: agentId.error }, 400);
  const name = asString(body?.name, "name", { max: 100 });
  if (!name.ok) return c.json({ error: name.error }, 400);
  const site = asOptionalString(body?.site, "site", { max: 100 });
  if (!site.ok) return c.json({ error: site.error }, 400);
  const role = asOptionalString(body?.role, "role", { max: 100 });
  if (!role.ok) return c.json({ error: role.error }, 400);
  const tags = asStringArray(body?.tags, "tags");
  if (!tags.ok) return c.json({ error: tags.error }, 400);
  const interval = asOptionalInt(body?.heartbeat_interval_seconds, "heartbeat_interval_seconds", {
    min: 30,
    max: 86400,
  });
  if (!interval.ok) return c.json({ error: interval.error }, 400);
  const grace = asOptionalInt(body?.grace_seconds, "grace_seconds", { min: 0, max: 86400 });
  if (!grace.ok) return c.json({ error: grace.error }, 400);

  // Connection details (control-plane-managed config). All optional; credentials
  // are stored only as references (env-var name / key path), never as secrets.
  const address = asOptionalString(body?.address, "address", { max: 255 });
  if (!address.ok) return c.json({ error: address.error }, 400);
  const username = asOptionalString(body?.username, "username", { max: 100 });
  if (!username.ok) return c.json({ error: username.error }, 400);
  const passwordEnv = asOptionalString(body?.password_env, "password_env", { max: 100 });
  if (!passwordEnv.ok) return c.json({ error: passwordEnv.error }, 400);
  const sshKeyPath = asOptionalString(body?.ssh_key_path, "ssh_key_path", { max: 255 });
  if (!sshKeyPath.ok) return c.json({ error: sshKeyPath.error }, 400);
  const tPrimary = asOptionalEnum(body?.transport_primary, "transport_primary", TRANSPORTS);
  if (!tPrimary.ok) return c.json({ error: tPrimary.error }, 400);
  const tFallback = asOptionalEnum(body?.transport_fallback, "transport_fallback", TRANSPORTS);
  if (!tFallback.ok) return c.json({ error: tFallback.error }, 400);
  const apiPort = asOptionalInt(body?.api_port, "api_port", { min: 1, max: 65535 });
  if (!apiPort.ok) return c.json({ error: apiPort.error }, 400);
  const sshPort = asOptionalInt(body?.ssh_port, "ssh_port", { min: 1, max: 65535 });
  if (!sshPort.ok) return c.json({ error: sshPort.error }, 400);
  const useTls = asOptionalBool(body?.use_tls, "use_tls");
  if (!useTls.ok) return c.json({ error: useTls.error }, 400);
  const useTlsInt = useTls.value === undefined ? null : useTls.value ? 1 : 0;

  const agent = await c.env.DB.prepare("SELECT id FROM agents WHERE id = ?1 AND disabled = 0")
    .bind(agentId.value)
    .first();
  if (!agent) return c.json({ error: "agent not found" }, 404);

  const existing = await c.env.DB.prepare(
    "SELECT id FROM devices WHERE agent_id = ?1 AND name = ?2",
  )
    .bind(agentId.value, name.value)
    .first<{ id: string }>();

  const id = existing?.id ?? newId("dev");
  const now = nowSeconds();
  const tagsJson = tags.value ? JSON.stringify(tags.value) : null;

  if (existing) {
    await c.env.DB.prepare(
      `UPDATE devices SET site = ?1, role = ?2, tags = ?3,
       heartbeat_interval_seconds = ?4, grace_seconds = ?5,
       address = ?6, username = ?7, password_env = ?8, ssh_key_path = ?9,
       transport_primary = ?10, transport_fallback = ?11,
       api_port = ?12, use_tls = ?13, ssh_port = ?14
       WHERE id = ?15`,
    )
      .bind(
        site.value ?? null,
        role.value ?? null,
        tagsJson,
        interval.value ?? null,
        grace.value ?? null,
        address.value ?? null,
        username.value ?? null,
        passwordEnv.value ?? null,
        sshKeyPath.value ?? null,
        tPrimary.value ?? null,
        tFallback.value ?? null,
        apiPort.value ?? null,
        useTlsInt,
        sshPort.value ?? null,
        id,
      )
      .run();
  } else {
    await c.env.DB.prepare(
      `INSERT INTO devices
       (id, agent_id, name, site, role, tags, heartbeat_interval_seconds, grace_seconds,
        address, username, password_env, ssh_key_path, transport_primary, transport_fallback,
        api_port, use_tls, ssh_port, last_status, created_at)
       VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16, ?17, 'unknown', ?18)`,
    )
      .bind(
        id,
        agentId.value,
        name.value,
        site.value ?? null,
        role.value ?? null,
        tagsJson,
        interval.value ?? null,
        grace.value ?? null,
        address.value ?? null,
        username.value ?? null,
        passwordEnv.value ?? null,
        sshKeyPath.value ?? null,
        tPrimary.value ?? null,
        tFallback.value ?? null,
        apiPort.value ?? null,
        useTlsInt,
        sshPort.value ?? null,
        now,
      )
      .run();
  }
  return c.json({ id, upserted: !existing });
});

admin.get("/devices", async (c) => {
  const { results } = await c.env.DB.prepare(
    `SELECT id, agent_id, name, site, role, tags, heartbeat_interval_seconds, grace_seconds,
            last_seen_at, last_status, last_status_changed_at, created_at
     FROM devices ORDER BY name`,
  ).all();
  return c.json({ devices: results });
});

admin.delete("/devices/:id", async (c) => {
  const res = await c.env.DB.prepare("DELETE FROM devices WHERE id = ?1").bind(c.req.param("id")).run();
  if ((res.meta.changes ?? 0) === 0) return c.json({ error: "not found" }, 404);
  return c.json({ ok: true });
});

// --- Alert routes ---------------------------------------------------------

admin.post("/alert-routes", async (c) => {
  const body = await c.req.json().catch(() => null);
  const name = asString(body?.name, "name", { max: 100 });
  if (!name.ok) return c.json({ error: name.error }, 400);
  const kind = asEnum(body?.kind, "kind", ROUTE_KINDS);
  if (!kind.ok) return c.json({ error: kind.error }, 400);
  const url = asString(body?.url, "url", { max: 1000, pattern: /^https?:\/\// });
  if (!url.ok) return c.json({ error: url.error }, 400);
  const events = asStringArray(body?.events, "events");
  if (!events.ok) return c.json({ error: events.error }, 400);
  if (events.value) {
    for (const ev of events.value) {
      if (!ALERT_KINDS.includes(ev as AlertKind)) {
        return c.json({ error: `unknown event '${ev}'` }, 400);
      }
    }
  }
  const minSeverity: Severity = body?.min_severity ?? "warning";
  if (!SEVERITIES.includes(minSeverity)) return c.json({ error: "invalid min_severity" }, 400);

  const id = newId("route");
  try {
    await c.env.DB.prepare(
      `INSERT INTO alert_routes (id, name, kind, url, events, min_severity, enabled, created_at)
       VALUES (?1, ?2, ?3, ?4, ?5, ?6, 1, ?7)`,
    )
      .bind(
        id,
        name.value,
        kind.value,
        url.value,
        events.value ? JSON.stringify(events.value) : null,
        minSeverity,
        nowSeconds(),
      )
      .run();
  } catch (err) {
    if (String(err).includes("UNIQUE")) return c.json({ error: "route name already exists" }, 409);
    throw err;
  }
  return c.json({ id, name: name.value }, 201);
});

admin.get("/alert-routes", async (c) => {
  const { results } = await c.env.DB.prepare(
    "SELECT id, name, kind, url, events, min_severity, enabled, created_at FROM alert_routes ORDER BY name",
  ).all();
  return c.json({ routes: results });
});

admin.delete("/alert-routes/:id", async (c) => {
  const res = await c.env.DB.prepare("DELETE FROM alert_routes WHERE id = ?1").bind(c.req.param("id")).run();
  if ((res.meta.changes ?? 0) === 0) return c.json({ error: "not found" }, 404);
  return c.json({ ok: true });
});

// --- Test alert -----------------------------------------------------------

admin.post("/alerts/test", async (c) => {
  const body = await c.req.json().catch(() => ({}));
  const message = typeof body?.message === "string" ? body.message : "Test alert from Mikrotik Minder";
  // Pass executionCtx so the outbound webhook fan-out runs via waitUntil()
  // and the API can respond immediately after persisting the alert row.
  // Otherwise a slow Slack/Discord sink would block this endpoint.
  const alertId = await fireAlert(
    c.env,
    {
      severity: "info",
      kind: "manual",
      title: message,
      payload: { source: "admin", note: "manual test" },
    },
    c.executionCtx,
  );
  return c.json({ ok: true, alert_id: alertId });
});

// --- Commands -------------------------------------------------------------
// The Pro UI enqueues operator-triggered actions here; the agent claims them
// via GET /v1/ingest/commands and reports back via POST .../result.

admin.post("/commands", async (c) => {
  const body = await c.req.json().catch(() => null);
  const deviceId = asString(body?.device_id, "device_id", { max: 100 });
  if (!deviceId.ok) return c.json({ error: deviceId.error }, 400);
  const kind = asEnum(body?.kind, "kind", COMMAND_KINDS);
  if (!kind.ok) return c.json({ error: kind.error }, 400);
  const scheduledFor = asOptionalInt(body?.scheduled_for, "scheduled_for", { min: 0 });
  if (!scheduledFor.ok) return c.json({ error: scheduledFor.error }, 400);
  // Derive requested_by from the X-Auth-Email header (set by Cloudflare Access)
  const rawEmail = c.req.header("X-Auth-Email") ?? "";
  const trimmed = rawEmail.trim();
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  const requestedBy = trimmed.length > 0 && trimmed.length <= 254 && emailRegex.test(trimmed) ? trimmed : "unknown";
  const params = body?.params;
  if (
    params !== undefined &&
    (typeof params !== "object" || params === null || Array.isArray(params))
  ) {
    return c.json({ error: "params must be an object" }, 400);
  }

  const dev = await c.env.DB.prepare("SELECT id, agent_id FROM devices WHERE id = ?1")
    .bind(deviceId.value)
    .first<{ id: string; agent_id: string }>();
  if (!dev) return c.json({ error: "device not found" }, 404);

  const id = newId("cmd");
  await c.env.DB.prepare(
    `INSERT INTO commands
       (id, device_id, agent_id, kind, params, status, scheduled_for, requested_by, created_at)
     VALUES (?1, ?2, ?3, ?4, ?5, 'pending', ?6, ?7, ?8)`,
  )
    .bind(
      id,
      dev.id,
      dev.agent_id,
      kind.value,
      params !== undefined ? JSON.stringify(params) : null,
      scheduledFor.value ?? null,
      requestedBy,
      nowSeconds(),
    )
    .run();
  return c.json({ id, status: "pending" }, 201);
});

// One-shot download of a sensitive-export artifact. Purged on read — the
// secret-bearing /export body is delivered exactly once and never re-served.
admin.get("/commands/:id/artifact", async (c) => {
  const id = c.req.param("id");
  const row = await c.env.DB.prepare(
    `WITH old AS (
       SELECT artifact FROM commands WHERE id = ?1 AND artifact IS NOT NULL
     )
     UPDATE commands SET artifact = NULL
     WHERE id = ?1 AND artifact IS NOT NULL
     RETURNING (SELECT artifact FROM old) AS artifact`
  )
    .bind(id)
    .first<{ artifact: string | null }>();
  if (!row || row.artifact === null) {
    // Either the row doesn't exist, or artifact was already NULL (already downloaded)
    const cmd = await c.env.DB.prepare("SELECT id, status FROM commands WHERE id = ?1").bind(id).first<{ id: string; status: string }>();
    if (!cmd) return c.json({ error: "not found" }, 404);
    if (cmd.status === "pending" || cmd.status === "claimed") {
      return c.json({ error: "command not yet ready" }, 202);
    }
    return c.json({ error: "no artifact — already downloaded, or none produced" }, 410);
  }
  return c.text(row.artifact, 200, {
    "content-type": "text/plain; charset=utf-8",
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
  });
});

// --- Backups --------------------------------------------------------------
// The agent uploads encrypted backups via PUT /v1/ingest/backups/...; these
// admin endpoints let the Pro UI list and download them. The body in R2 is
// already AES-encrypted by RouterOS, so the worker never holds plaintext.

admin.get("/devices/:id/backups", async (c) => {
  const id = c.req.param("id");
  const { results } = await c.env.DB.prepare(
    `SELECT id, file_name, size_bytes, sha256, created_at
       FROM backup_files
      WHERE device_id = ?1
   ORDER BY created_at DESC
      LIMIT 200`,
  )
    .bind(id)
    .all();
  return c.json({ backups: results });
});

// Stream the encrypted backup body from R2. The Pro UI proxies this so the
// browser never talks to R2 directly. No caching headers — the body is a
// sensitive ciphertext blob, and we don't want intermediates retaining it.
admin.get("/backups/:id/download", async (c) => {
  const id = c.req.param("id");
  const row = await c.env.DB.prepare(
    "SELECT file_name, r2_key, sha256 FROM backup_files WHERE id = ?1",
  )
    .bind(id)
    .first<{ file_name: string; r2_key: string; sha256: string }>();
  if (!row) return c.json({ error: "not found" }, 404);

  const obj = await c.env.BACKUPS.get(row.r2_key);
  if (!obj) {
    // D1 row exists but R2 body is missing — orphan. Surface as 410 so the UI
    // can prune the listing without 5xx-style panic.
    return c.json({ error: "backup body missing from storage" }, 410);
  }
  // Use the live R2 object size so a stale catalog row can't cause clients to
  // truncate or hang. `obj.size` is set by R2 on PUT.
  const headers: Record<string, string> = {
    "content-type": "application/octet-stream",
    "content-disposition": `attachment; filename="${row.file_name}"`,
    "x-content-sha256": row.sha256,
    "Cache-Control": "no-store",
  };
  if (typeof obj.size === "number") {
    headers["content-length"] = String(obj.size);
  }
  return new Response(obj.body, { headers });
});

export default admin;