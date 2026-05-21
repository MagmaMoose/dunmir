import { Hono } from "hono";
import { requireAdmin } from "../auth";
import type { AppContext } from "../env";
import { numEnv } from "../env";

const read = new Hono<AppContext>();
read.use("*", requireAdmin());

read.get("/devices", async (c) => {
  const { results } = await c.env.DB.prepare(
    `SELECT d.id, d.agent_id, a.name AS agent_name, d.name, d.site, d.role, d.tags,
            d.heartbeat_interval_seconds, d.grace_seconds,
            d.last_seen_at, d.last_status, d.last_status_changed_at, d.created_at
     FROM devices d JOIN agents a ON a.id = d.agent_id
     ORDER BY d.name`,
  ).all();
  return c.json({ devices: results });
});

read.get("/jobs", async (c) => {
  const limit = Math.min(Math.max(Number(c.req.query("limit") ?? 100), 1), 500);
  const status = c.req.query("status");
  const kind = c.req.query("kind");
  const deviceId = c.req.query("device_id");

  const conditions: string[] = [];
  const binds: (string | number)[] = [];
  if (status) {
    conditions.push(`status = ?${binds.length + 1}`);
    binds.push(status);
  }
  if (kind) {
    conditions.push(`kind = ?${binds.length + 1}`);
    binds.push(kind);
  }
  if (deviceId) {
    conditions.push(`device_id = ?${binds.length + 1}`);
    binds.push(deviceId);
  }
  const where = conditions.length ? `WHERE ${conditions.join(" AND ")}` : "";
  binds.push(limit);
  const sql = `SELECT id, agent_id, device_id, kind, status, started_at, finished_at, summary, details, created_at
              FROM jobs ${where}
              ORDER BY finished_at DESC LIMIT ?${binds.length}`;
  const { results } = await c.env.DB.prepare(sql).bind(...binds).all();
  return c.json({ jobs: results });
});

read.get("/alerts", async (c) => {
  const limit = Math.min(Math.max(Number(c.req.query("limit") ?? 100), 1), 500);
  const sql = `SELECT id, severity, kind, agent_id, device_id, job_id, title, payload, created_at
               FROM alerts ORDER BY created_at DESC LIMIT ?1`;
  const { results } = await c.env.DB.prepare(sql).bind(limit).all();
  return c.json({ alerts: results });
});

read.get("/health", (c) => {
  return c.json({
    ok: true,
    name: "mikrotik-minder",
    dashboard_rows: numEnv(c.env.DASHBOARD_ROWS, 50),
  });
});

export default read;
