import { Hono } from "hono";
import { requireAgent } from "../auth";
import type { AppContext } from "../env";
import { newId, nowSeconds } from "../ids";
import { fireAlert } from "../notify";
import {
  asEnum,
  asInt,
  asOptionalString,
  asString,
  DEVICE_STATUSES,
  JOB_KINDS,
  JOB_STATUSES,
  type DeviceStatus,
} from "../schema";

const ingest = new Hono<AppContext>();
ingest.use("*", requireAgent());

async function findOrCreateDevice(
  env: AppContext["Bindings"],
  agentId: string,
  identifier: string,
): Promise<{ id: string; name: string; created: boolean; previous_status: DeviceStatus }> {
  let row = await env.DB.prepare(
    "SELECT id, name, last_status FROM devices WHERE agent_id = ?1 AND (name = ?2 OR id = ?2)",
  )
    .bind(agentId, identifier)
    .first<{ id: string; name: string; last_status: DeviceStatus }>();

  if (row) return { id: row.id, name: row.name, created: false, previous_status: row.last_status };

  const id = newId("dev");
  await env.DB.prepare(
    `INSERT INTO devices (id, agent_id, name, last_status, created_at) VALUES (?1, ?2, ?3, 'unknown', ?4)`,
  )
    .bind(id, agentId, identifier, nowSeconds())
    .run();
  return { id, name: identifier, created: true, previous_status: "unknown" };
}

ingest.post("/heartbeat", async (c) => {
  const agentId = c.get("agentId")!;
  const body = await c.req.json().catch(() => null);
  const device = asString(body?.device, "device", { max: 100 });
  if (!device.ok) return c.json({ error: device.error }, 400);
  let status: DeviceStatus = "ok";
  if (body?.status !== undefined) {
    const s = asEnum<DeviceStatus>(body.status, "status", DEVICE_STATUSES);
    if (!s.ok) return c.json({ error: s.error }, 400);
    status = s.value;
  }

  const dev = await findOrCreateDevice(c.env, agentId, device.value);
  const now = nowSeconds();
  const statusChanged = dev.previous_status !== status;
  await c.env.DB.prepare(
    `UPDATE devices SET last_seen_at = ?1, last_status = ?2,
       last_status_changed_at = CASE WHEN ?3 = 1 THEN ?1 ELSE last_status_changed_at END
     WHERE id = ?4`,
  )
    .bind(now, status, statusChanged ? 1 : 0, dev.id)
    .run();
  await c.env.DB.prepare("UPDATE agents SET last_seen_at = ?1 WHERE id = ?2").bind(now, agentId).run();

  if (dev.previous_status === "down" && status !== "down") {
    await fireAlert(
      c.env,
      {
        severity: "info",
        kind: "heartbeat_recovered",
        agent_id: agentId,
        device_id: dev.id,
        title: `${dev.name} is back online`,
        payload: { device: dev.name, previous_status: dev.previous_status, status },
      },
      c.executionCtx,
    );
  }

  return c.json({ ok: true, device_id: dev.id, created: dev.created });
});

ingest.post("/jobs", async (c) => {
  const agentId = c.get("agentId")!;
  const body = await c.req.json().catch(() => null);
  const kind = asEnum(body?.kind, "kind", JOB_KINDS);
  if (!kind.ok) return c.json({ error: kind.error }, 400);
  const status = asEnum(body?.status, "status", JOB_STATUSES);
  if (!status.ok) return c.json({ error: status.error }, 400);
  const started = asInt(body?.started_at, "started_at", { min: 0 });
  if (!started.ok) return c.json({ error: started.error }, 400);
  const finished = asInt(body?.finished_at, "finished_at", { min: 0 });
  if (!finished.ok) return c.json({ error: finished.error }, 400);
  if (finished.value < started.value) {
    return c.json({ error: "finished_at must be >= started_at" }, 400);
  }
  const summary = asOptionalString(body?.summary, "summary", { max: 500 });
  if (!summary.ok) return c.json({ error: summary.error }, 400);
  const deviceName = asOptionalString(body?.device, "device", { max: 100 });
  if (!deviceName.ok) return c.json({ error: deviceName.error }, 400);

  let deviceId: string | null = null;
  let deviceLabel: string | null = null;
  if (deviceName.value) {
    const dev = await findOrCreateDevice(c.env, agentId, deviceName.value);
    deviceId = dev.id;
    deviceLabel = dev.name;
  }

  const id = newId("job");
  const detailsJson = body?.details !== undefined ? JSON.stringify(body.details) : null;
  await c.env.DB.prepare(
    `INSERT INTO jobs (id, agent_id, device_id, kind, status, started_at, finished_at, summary, details, created_at)
     VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)`,
  )
    .bind(
      id,
      agentId,
      deviceId,
      kind.value,
      status.value,
      started.value,
      finished.value,
      summary.value ?? null,
      detailsJson,
      nowSeconds(),
    )
    .run();
  await c.env.DB.prepare("UPDATE agents SET last_seen_at = ?1 WHERE id = ?2")
    .bind(nowSeconds(), agentId)
    .run();

  if (status.value === "failed") {
    await fireAlert(
      c.env,
      {
        severity:
          kind.value === "update_apply" || kind.value === "firmware_align" ? "critical" : "warning",
        kind:
          kind.value === "update_apply" || kind.value === "firmware_align"
            ? "update_failed"
            : "job_failed",
        agent_id: agentId,
        device_id: deviceId ?? undefined,
        job_id: id,
        title: `${kind.value} failed${deviceLabel ? ` on ${deviceLabel}` : ""}`,
        payload: { kind: kind.value, summary: summary.value, device: deviceLabel },
      },
      c.executionCtx,
    );
  } else if (kind.value === "drift" && status.value === "warning") {
    await fireAlert(
      c.env,
      {
        severity: "warning",
        kind: "drift_detected",
        agent_id: agentId,
        device_id: deviceId ?? undefined,
        job_id: id,
        title: `Config drift detected${deviceLabel ? ` on ${deviceLabel}` : ""}`,
        payload: { summary: summary.value, device: deviceLabel },
      },
      c.executionCtx,
    );
  } else if (
    (kind.value === "update_check" || kind.value === "firmware_align") &&
    status.value === "warning"
  ) {
    await fireAlert(
      c.env,
      {
        severity: "warning",
        kind: "update_available",
        agent_id: agentId,
        device_id: deviceId ?? undefined,
        job_id: id,
        title: `${kind.value === "firmware_align" ? "Firmware mismatch" : "Update available"}${deviceLabel ? ` on ${deviceLabel}` : ""}`,
        payload: { kind: kind.value, summary: summary.value, device: deviceLabel },
      },
      c.executionCtx,
    );
  }

  return c.json({ ok: true, job_id: id }, 201);
});

export default ingest;
