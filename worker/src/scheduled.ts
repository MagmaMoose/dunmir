import type { Env } from "./env";
import { numEnv } from "./env";
import { nowSeconds } from "./ids";
import { fireAlert } from "./notify";

interface DeviceRow {
  id: string;
  agent_id: string;
  name: string;
  site: string | null;
  last_seen_at: number | null;
  heartbeat_interval_seconds: number | null;
  grace_seconds: number | null;
}

export async function runScheduledSweep(env: Env, ctx: ExecutionContext): Promise<void> {
  const defaultInterval = numEnv(env.DEFAULT_HEARTBEAT_INTERVAL_SECONDS, 3600);
  const defaultGrace = numEnv(env.DEFAULT_GRACE_SECONDS, 600);
  const now = nowSeconds();

  const { results } = await env.DB.prepare(
    `SELECT id, agent_id, name, site, last_seen_at, heartbeat_interval_seconds, grace_seconds
     FROM devices
     WHERE last_status != 'down' AND last_seen_at IS NOT NULL`,
  ).all<DeviceRow>();

  const stale = results.filter((d) => {
    const interval = d.heartbeat_interval_seconds ?? defaultInterval;
    const grace = d.grace_seconds ?? defaultGrace;
    return d.last_seen_at !== null && now - d.last_seen_at > interval + grace;
  });

  if (stale.length === 0) return;

  for (const d of stale) {
    await env.DB.prepare(
      `UPDATE devices SET last_status = 'down', last_status_changed_at = ?1 WHERE id = ?2`,
    )
      .bind(now, d.id)
      .run();
  }

  await Promise.all(
    stale.map((d) => {
      const lastSeenAgo = d.last_seen_at ? now - d.last_seen_at : null;
      return fireAlert(
        env,
        {
          severity: "critical",
          kind: "heartbeat_missed",
          agent_id: d.agent_id,
          device_id: d.id,
          title: `${d.name} missed heartbeat`,
          payload: {
            device: d.name,
            site: d.site,
            last_seen_at: d.last_seen_at,
            last_seen_seconds_ago: lastSeenAgo,
            expected_interval_seconds: d.heartbeat_interval_seconds ?? defaultInterval,
            grace_seconds: d.grace_seconds ?? defaultGrace,
          },
        },
        ctx,
      );
    }),
  );
}
