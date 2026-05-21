import { Hono } from "hono";
import type { AppContext } from "../env";
import { generateAgentToken, hashToken, requireAdmin } from "../auth";
import { newId, nowSeconds } from "../ids";
import {
  ALERT_KINDS,
  asEnum,
  asInt,
  asOptionalInt,
  asOptionalString,
  asString,
  asStringArray,
  ROUTE_KINDS,
  SEVERITIES,
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
       heartbeat_interval_seconds = ?4, grace_seconds = ?5
       WHERE id = ?6`,
    )
      .bind(site.value ?? null, role.value ?? null, tagsJson, interval.value ?? null, grace.value ?? null, id)
      .run();
  } else {
    await c.env.DB.prepare(
      `INSERT INTO devices
       (id, agent_id, name, site, role, tags, heartbeat_interval_seconds, grace_seconds, last_status, created_at)
       VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, 'unknown', ?9)`,
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
  const alertId = await fireAlert(c.env, {
    severity: "info",
    kind: "manual",
    title: message,
    payload: { source: "admin", note: "manual test" },
  });
  return c.json({ ok: true, alert_id: alertId });
});

export default admin;
