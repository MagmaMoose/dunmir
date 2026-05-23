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
        severity: "info",
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
  } else if (status.value === "success" && kind.value === "backup") {
    await fireAlert(
      c.env,
      {
        severity: "info",
        kind: "backup_succeeded",
        agent_id: agentId,
        device_id: deviceId ?? undefined,
        job_id: id,
        title: `Backup completed${deviceLabel ? ` for ${deviceLabel}` : ""}`,
        payload: { device: deviceLabel, summary: summary.value },
      },
      c.executionCtx,
    );
  } else if (status.value === "success" && kind.value === "update_apply") {
    await fireAlert(
      c.env,
      {
        severity: "info",
        kind: "update_applied",
        agent_id: agentId,
        device_id: deviceId ?? undefined,
        job_id: id,
        title: `Update applied${deviceLabel ? ` to ${deviceLabel}` : ""}`,
        payload: { device: deviceLabel, summary: summary.value },
      },
      c.executionCtx,
    );
  }

  return c.json({ ok: true, job_id: id }, 201);
});

// Agent poll: claim this agent's due, pending commands. The UPDATE...RETURNING
// flips them to 'claimed' atomically, so a re-poll mid-run never hands the same
// command out twice.
ingest.get("/commands", async (c) => {
  const agentId = c.get("agentId")!;
  const now = nowSeconds();
  const { results } = await c.env.DB.prepare(
    `UPDATE commands SET status = 'claimed', claimed_at = ?1
     WHERE id IN (
       SELECT id FROM commands
       WHERE agent_id = ?2 AND status = 'pending'
         AND (scheduled_for IS NULL OR scheduled_for <= ?1)
       ORDER BY created_at LIMIT 20
     )
     RETURNING commands.id, commands.device_id, commands.kind, commands.params,
       (SELECT name FROM devices WHERE id = commands.device_id) AS device_name`,
  )
    .bind(now, agentId)
    .all<{ id: string; device_id: string; kind: string; params: string | null; device_name: string }>();

  const commands = [];
  for (const r of results) {
    let params: Record<string, unknown> = {};
    if (r.params) {
      try {
        params = JSON.parse(r.params);
      } catch {
        params = {};
      }
    }
    commands.push({
      id: r.id,
      device: r.device_name,
      kind: r.kind,
      params,
    });
  }
  return c.json({ commands });
});

// Agent reports a claimed command's outcome. `artifact` carries a one-shot
// sensitive-export body (downloaded once via GET /v1/admin/commands/:id/artifact).
ingest.post("/commands/:id/result", async (c) => {
  const agentId = c.get("agentId")!;
  const id = c.req.param("id");
  const body = await c.req.json().catch(() => null);
  const status = asEnum(body?.status, "status", ["succeeded", "failed"] as const);
  if (!status.ok) return c.json({ error: status.error }, 400);
  const result = body?.result;
  if (result !== undefined && (typeof result !== "object" || result === null || Array.isArray(result))) {
    return c.json({ error: "result must be an object" }, 400);
  }
  // Use a custom validator that preserves the original string verbatim (no trimming)
  const artifact = validateArtifact(body?.artifact);
  if (!artifact.ok) return c.json({ error: artifact.error }, 400);

  // Artifacts only make sense for `sensitive_export`. Reject early when the
  // agent tries to attach a body to any other kind so we never accidentally
  // persist large/sensitive blobs against e.g. a backup command. The cost is
  // one extra read on the result-report path, which isn't hot.
  if (artifact.value !== null) {
    const cmd = await c.env.DB.prepare(
      "SELECT kind FROM commands WHERE id = ?1 AND agent_id = ?2 AND status = 'claimed'",
    )
      .bind(id, agentId)
      .first<{ kind: string }>();
    if (!cmd) {
      return c.json({ error: "command not found, not yours, or not in 'claimed' state" }, 404);
    }
    if (cmd.kind !== "sensitive_export") {
      return c.json(
        { error: `artifact only allowed for sensitive_export, not ${cmd.kind}` },
        400,
      );
    }
  }

  const res = await c.env.DB.prepare(
    `UPDATE commands SET status = ?1, result = ?2, artifact = ?3, finished_at = ?4
     WHERE id = ?5 AND agent_id = ?6 AND status = 'claimed'`,
  )
    .bind(
      status.value,
      result !== undefined ? JSON.stringify(result) : null,
      artifact.value ?? null,
      nowSeconds(),
      id,
      agentId,
    )
    .run();
  if ((res.meta.changes ?? 0) === 0) {
    return c.json({ error: "command not found, not yours, or not in 'claimed' state" }, 404);
  }
  return c.json({ ok: true });
});

function validateArtifact(value: unknown): { ok: true; value: string | null } | { ok: false; error: string } {
  if (value === undefined || value === null) {
    return { ok: true, value: null };
  }
  if (typeof value !== "string") {
    return { ok: false, error: "artifact must be a string" };
  }
  if (value.length > 5_000_000) {
    return { ok: false, error: "artifact must be at most 5,000,000 characters" };
  }
  return { ok: true, value };
}

// --- Backup uploads --------------------------------------------------------
//
// Agent PUTs each successful backup's encrypted body here as the raw request
// body (`application/octet-stream`). The worker writes ciphertext to R2 and
// catalogues the upload in `backup_files` so the Pro UI can list + download
// it later. Limits:
//
//   - max 64 MiB per upload (well above typical RouterOS configs)
//   - sha256 sent as a query string + matched against R2's MD5 we cannot
//     reproduce, so we re-hash on the worker and reject mismatches (catches
//     corruption-in-flight without trusting the client header)
//   - `device` must match an agent-owned device; otherwise 403
//   - `file_name` must look like a backup filename (no slashes, .backup suffix)
//   - duplicate file_name for the same device → idempotent (200 + existing id)

const MAX_BACKUP_BYTES = 64 * 1024 * 1024;
const BACKUP_NAME_RE = /^[A-Za-z0-9._-]+\.backup$/;

ingest.put("/backups/:device/:filename", async (c) => {
  const agentId = c.get("agentId")!;
  const deviceName = c.req.param("device");
  const fileName = c.req.param("filename");
  const claimedSha = (c.req.query("sha256") ?? "").toLowerCase();

  if (!BACKUP_NAME_RE.test(fileName)) {
    return c.json({ error: "file_name must match [A-Za-z0-9._-]+\\.backup" }, 400);
  }
  if (claimedSha && !/^[a-f0-9]{64}$/.test(claimedSha)) {
    return c.json({ error: "sha256 must be 64 lowercase hex chars" }, 400);
  }

  const dev = await c.env.DB.prepare(
    "SELECT id FROM devices WHERE agent_id = ?1 AND name = ?2",
  )
    .bind(agentId, deviceName)
    .first<{ id: string }>();
  if (!dev) return c.json({ error: "device not found for this agent" }, 404);

  // Idempotency: if this filename is already catalogued for this device,
  // return the existing row instead of double-writing R2.
  const existing = await c.env.DB.prepare(
    "SELECT id FROM backup_files WHERE device_id = ?1 AND file_name = ?2",
  )
    .bind(dev.id, fileName)
    .first<{ id: string }>();
  if (existing) return c.json({ id: existing.id, deduped: true });

  // Buffer the body so we can both hash it and write to R2. Workers cap us
  // at 100 MiB anyway; we additionally enforce MAX_BACKUP_BYTES.
  const buf = await c.req.arrayBuffer();
  if (buf.byteLength === 0) return c.json({ error: "empty body" }, 400);
  if (buf.byteLength > MAX_BACKUP_BYTES) {
    return c.json(
      { error: `body exceeds ${MAX_BACKUP_BYTES} bytes (got ${buf.byteLength})` },
      413,
    );
  }
  const digest = await crypto.subtle.digest("SHA-256", buf);
  const computedSha = [...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  if (claimedSha && claimedSha !== computedSha) {
    return c.json(
      { error: "sha256 mismatch", claimed: claimedSha, computed: computedSha },
      400,
    );
  }

  const r2Key = `backups/${dev.id}/${fileName}`;
  await c.env.BACKUPS.put(r2Key, buf, {
    httpMetadata: { contentType: "application/octet-stream" },
    customMetadata: {
      device_id: dev.id,
      device_name: deviceName,
      agent_id: agentId,
      sha256: computedSha,
    },
  });

  const id = newId("bkp");
  await c.env.DB.prepare(
    `INSERT INTO backup_files (id, agent_id, device_id, file_name, r2_key, size_bytes, sha256, created_at)
     VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)`,
  )
    .bind(id, agentId, dev.id, fileName, r2Key, buf.byteLength, computedSha, nowSeconds())
    .run();

  return c.json(
    { id, r2_key: r2Key, size_bytes: buf.byteLength, sha256: computedSha },
    201,
  );
});

// Allow the agent to drop a catalog row when retention prunes it locally.
// The body is gone either way; this keeps D1/R2 in sync with the PVC.
ingest.delete("/backups/:id", async (c) => {
  const agentId = c.get("agentId")!;
  const id = c.req.param("id");
  const row = await c.env.DB.prepare(
    "SELECT r2_key FROM backup_files WHERE id = ?1 AND agent_id = ?2",
  )
    .bind(id, agentId)
    .first<{ r2_key: string }>();
  if (!row) return c.json({ error: "backup not found for this agent" }, 404);

  await c.env.BACKUPS.delete(row.r2_key);
  await c.env.DB.prepare("DELETE FROM backup_files WHERE id = ?1").bind(id).run();
  return c.json({ ok: true });
});

export default ingest;
