import type { Env } from "./env";
import { newId, nowSeconds } from "./ids";
import { meetsSeverity, type AlertKind, type RouteKind, type Severity } from "./schema";

export interface AlertInput {
  severity: Severity;
  kind: AlertKind;
  title: string;
  payload: Record<string, unknown>;
  agent_id?: string;
  device_id?: string;
  job_id?: string;
}

export interface StoredAlert extends AlertInput {
  id: string;
  created_at: number;
}

interface RouteRow {
  id: string;
  name: string;
  kind: RouteKind;
  url: string;
  events: string | null;
  min_severity: Severity;
  enabled: number;
}

const SEVERITY_COLOR_SLACK: Record<Severity, string> = {
  info: "#3aa3e3",
  warning: "#f2c744",
  critical: "#d72631",
};

const SEVERITY_COLOR_DISCORD: Record<Severity, number> = {
  info: 0x3aa3e3,
  warning: 0xf2c744,
  critical: 0xd72631,
};

export async function fireAlert(
  env: Env,
  input: AlertInput,
  ctx?: { waitUntil(p: Promise<unknown>): void },
): Promise<string> {
  const id = newId("alert");
  const created = nowSeconds();
  await env.DB.prepare(
    `INSERT INTO alerts (id, severity, kind, agent_id, device_id, job_id, title, payload, created_at)
     VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)`,
  )
    .bind(
      id,
      input.severity,
      input.kind,
      input.agent_id ?? null,
      input.device_id ?? null,
      input.job_id ?? null,
      input.title,
      JSON.stringify(input.payload),
      created,
    )
    .run();

  const stored: StoredAlert = { ...input, id, created_at: created };
  const dispatch = deliverAlert(env, stored);
  if (ctx) ctx.waitUntil(dispatch);
  else await dispatch;
  return id;
}

export async function deliverAlert(env: Env, alert: StoredAlert): Promise<void> {
  const routes = await pickRoutes(env, alert);
  const work: Promise<unknown>[] = routes.map((r) => deliverToRoute(env, alert, r));
  // The env-configured Slack bot integration fires for every alert, alongside
  // any DB-configured webhook/discord routes.
  if (env.SLACK_BOT_TOKEN) {
    work.push(deliverToSlackBot(env, alert));
  }
  if (work.length === 0) return;
  await Promise.all(work);
}

/**
 * Post an alert to Slack via chat.postMessage using a bot token.
 *
 * Channel is chosen by severity: `info` → SLACK_SUCCESS_CHANNEL (good news),
 * `warning`/`critical` → SLACK_FAILURE_CHANNEL (needs attention). An unset
 * channel for a given class is simply skipped.
 */
async function deliverToSlackBot(env: Env, alert: StoredAlert): Promise<void> {
  const channel =
    alert.severity === "info" ? env.SLACK_SUCCESS_CHANNEL : env.SLACK_FAILURE_CHANNEL;
  if (!channel) return; // no channel configured for this severity class

  try {
    const res = await fetch("https://slack.com/api/chat.postMessage", {
      method: "POST",
      headers: {
        authorization: `Bearer ${env.SLACK_BOT_TOKEN}`,
        "content-type": "application/json; charset=utf-8",
      },
      body: JSON.stringify(slackBotMessage(alert, channel)),
    });
    // Slack returns HTTP 200 even for logical failures; the body carries `ok`.
    const data = (await res.json().catch(() => ({}))) as { ok?: boolean; error?: string };
    if (!res.ok || !data.ok) {
      console.error("slack chat.postMessage failed", res.status, data.error ?? "(no body)");
    }
  } catch (err) {
    console.error("slack chat.postMessage threw", err instanceof Error ? err.message : err);
  }
}

async function pickRoutes(env: Env, alert: StoredAlert): Promise<RouteRow[]> {
  const { results } = await env.DB.prepare(
    "SELECT id, name, kind, url, events, min_severity, enabled FROM alert_routes WHERE enabled = 1",
  ).all<RouteRow>();
  return results.filter((r) => {
    if (!meetsSeverity(alert.severity, r.min_severity)) return false;
    if (r.events) {
      try {
        const list = JSON.parse(r.events) as string[];
        if (!list.includes(alert.kind)) return false;
      } catch {
        return false;
      }
    }
    return true;
  });
}

async function deliverToRoute(env: Env, alert: StoredAlert, route: RouteRow): Promise<void> {
  const body = formatBody(alert, route.kind);
  let status: "ok" | "failed" = "failed";
  let httpStatus: number | null = null;
  let error: string | null = null;
  try {
    const res = await fetch(route.url, {
      method: "POST",
      headers: { "content-type": "application/json", "user-agent": "mikrotik-minder/0.1" },
      body: JSON.stringify(body),
    });
    httpStatus = res.status;
    status = res.ok ? "ok" : "failed";
    if (!res.ok) error = `HTTP ${res.status}`;
  } catch (err) {
    error = err instanceof Error ? err.message : String(err);
  }

  await env.DB.prepare(
    `INSERT INTO alert_deliveries (id, alert_id, route_id, status, http_status, error, delivered_at)
     VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)`,
  )
    .bind(newId("dlv"), alert.id, route.id, status, httpStatus, error, nowSeconds())
    .run();
}

function formatBody(alert: StoredAlert, kind: RouteKind): unknown {
  if (kind === "slack") return slackBody(alert);
  if (kind === "discord") return discordBody(alert);
  return genericBody(alert);
}

function slackBody(alert: StoredAlert) {
  return {
    text: `Mikrotik Minder: ${alert.kind}`,
    attachments: [
      {
        color: SEVERITY_COLOR_SLACK[alert.severity],
        title: alert.title,
        fields: [
          { title: "Severity", value: alert.severity, short: true },
          { title: "Kind", value: alert.kind, short: true },
          ...renderFields(alert),
        ],
        footer: "mikrotik-minder",
        ts: alert.created_at,
      },
    ],
  };
}

function discordBody(alert: StoredAlert) {
  return {
    username: "Mikrotik Minder",
    embeds: [
      {
        title: alert.title,
        color: SEVERITY_COLOR_DISCORD[alert.severity],
        fields: [
          { name: "Severity", value: alert.severity, inline: true },
          { name: "Kind", value: alert.kind, inline: true },
          ...renderFields(alert).map((f) => ({
            name: f.title,
            value: f.value,
            inline: f.short ?? false,
          })),
        ],
        timestamp: new Date(alert.created_at * 1000).toISOString(),
      },
    ],
  };
}

function genericBody(alert: StoredAlert) {
  return {
    id: alert.id,
    severity: alert.severity,
    kind: alert.kind,
    title: alert.title,
    agent_id: alert.agent_id ?? null,
    device_id: alert.device_id ?? null,
    job_id: alert.job_id ?? null,
    payload: alert.payload,
    created_at: alert.created_at,
  };
}

const SEVERITY_EMOJI: Record<Severity, string> = {
  info: ":white_check_mark:",
  warning: ":warning:",
  critical: ":rotating_light:",
};

/** Block Kit message for the Slack Web API `chat.postMessage`. */
function slackBotMessage(alert: StoredAlert, channel: string) {
  const detailLines = renderFields(alert)
    .map((f) => `*${f.title}:* ${f.value}`)
    .join("\n");
  return {
    channel,
    // `text` is the notification fallback (lockscreen / a11y).
    text: `${alert.severity.toUpperCase()} · ${alert.title}`,
    blocks: [
      {
        type: "header",
        text: {
          type: "plain_text",
          text: `${SEVERITY_EMOJI[alert.severity]} ${alert.title}`.slice(0, 150),
          emoji: true,
        },
      },
      {
        type: "section",
        fields: [
          { type: "mrkdwn", text: `*Severity:*\n${alert.severity}` },
          { type: "mrkdwn", text: `*Kind:*\n${alert.kind}` },
        ],
      },
      ...(detailLines
        ? [{ type: "section", text: { type: "mrkdwn", text: detailLines.slice(0, 2900) } }]
        : []),
      {
        type: "context",
        elements: [
          {
            type: "mrkdwn",
            text: `mikrotik-minder · alert \`${alert.id}\` · <!date^${alert.created_at}^{date_short_pretty} {time}|just now>`,
          },
        ],
      },
    ],
  };
}

function renderFields(alert: StoredAlert): { title: string; value: string; short?: boolean }[] {
  const out: { title: string; value: string; short?: boolean }[] = [];
  for (const [k, v] of Object.entries(alert.payload)) {
    if (v == null) continue;
    const str = typeof v === "string" ? v : JSON.stringify(v);
    if (str.length > 200) continue;
    out.push({ title: k, value: str, short: str.length < 40 });
  }
  return out;
}
