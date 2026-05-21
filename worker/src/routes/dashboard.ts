import type { Context } from "hono";
import { Hono } from "hono";
import { getCookie, setCookie, deleteCookie } from "hono/cookie";
import type { AppContext } from "../env";
import { constantTimeEqual } from "../auth";
import { numEnv } from "../env";

const dashboard = new Hono<AppContext>();
const SESSION_COOKIE = "mtm_session";
const SESSION_TTL_SECONDS = 8 * 60 * 60;

function isAuthed(c: Context<AppContext>): boolean {
  const cookie = getCookie(c, SESSION_COOKIE);
  if (!cookie || !c.env.ADMIN_TOKEN) return false;
  return constantTimeEqual(cookie, c.env.ADMIN_TOKEN);
}

dashboard.post("/login", async (c) => {
  const form = await c.req.parseBody();
  const token = typeof form.token === "string" ? form.token : "";
  if (!token || !c.env.ADMIN_TOKEN || !constantTimeEqual(token, c.env.ADMIN_TOKEN)) {
    return c.html(loginPage("Invalid token"), 401);
  }
  setCookie(c, SESSION_COOKIE, token, {
    httpOnly: true,
    secure: true,
    sameSite: "Lax",
    path: "/",
    maxAge: SESSION_TTL_SECONDS,
  });
  return c.redirect("/", 302);
});

dashboard.post("/logout", (c) => {
  deleteCookie(c, SESSION_COOKIE, { path: "/" });
  return c.redirect("/", 302);
});

dashboard.get("/", async (c) => {
  if (!isAuthed(c)) return c.html(loginPage());
  const rows = numEnv(c.env.DASHBOARD_ROWS, 50);

  const [devicesRes, jobsRes, alertsRes, agentsRes] = await Promise.all([
    c.env.DB.prepare(
      `SELECT d.id, d.name, d.site, d.role, d.last_seen_at, d.last_status,
              d.heartbeat_interval_seconds, d.grace_seconds, a.name AS agent_name
       FROM devices d JOIN agents a ON a.id = d.agent_id
       ORDER BY CASE d.last_status WHEN 'down' THEN 0 WHEN 'degraded' THEN 1
               WHEN 'unknown' THEN 2 ELSE 3 END, d.name`,
    ).all<DeviceRow>(),
    c.env.DB.prepare(
      `SELECT j.id, j.kind, j.status, j.started_at, j.finished_at, j.summary,
              d.name AS device_name
       FROM jobs j LEFT JOIN devices d ON d.id = j.device_id
       ORDER BY j.finished_at DESC LIMIT ?1`,
    )
      .bind(rows)
      .all<JobRow>(),
    c.env.DB.prepare(
      `SELECT a.id, a.severity, a.kind, a.title, a.created_at, d.name AS device_name
       FROM alerts a LEFT JOIN devices d ON d.id = a.device_id
       ORDER BY a.created_at DESC LIMIT ?1`,
    )
      .bind(rows)
      .all<AlertRow>(),
    c.env.DB.prepare(
      `SELECT id, name, last_seen_at, disabled FROM agents ORDER BY name`,
    ).all<AgentRow>(),
  ]);

  return c.html(
    dashboardPage({
      devices: devicesRes.results,
      jobs: jobsRes.results,
      alerts: alertsRes.results,
      agents: agentsRes.results,
      defaultInterval: numEnv(c.env.DEFAULT_HEARTBEAT_INTERVAL_SECONDS, 3600),
      defaultGrace: numEnv(c.env.DEFAULT_GRACE_SECONDS, 600),
    }),
  );
});

interface DeviceRow {
  id: string;
  name: string;
  site: string | null;
  role: string | null;
  last_seen_at: number | null;
  last_status: string;
  heartbeat_interval_seconds: number | null;
  grace_seconds: number | null;
  agent_name: string;
}
interface JobRow {
  id: string;
  kind: string;
  status: string;
  started_at: number;
  finished_at: number;
  summary: string | null;
  device_name: string | null;
}
interface AlertRow {
  id: string;
  severity: string;
  kind: string;
  title: string;
  created_at: number;
  device_name: string | null;
}
interface AgentRow {
  id: string;
  name: string;
  last_seen_at: number | null;
  disabled: number;
}

function escapeHtml(s: unknown): string {
  if (s === null || s === undefined) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function relTime(secs: number | null): string {
  if (secs === null || secs === undefined) return "never";
  const delta = Math.floor(Date.now() / 1000) - secs;
  if (delta < 60) return `${delta}s ago`;
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
  return `${Math.floor(delta / 86400)}d ago`;
}

const STYLES = `
  :root {
    --bg: #0b1020;
    --panel: #131a32;
    --panel-2: #1a2240;
    --text: #e6e9f2;
    --muted: #8b93ad;
    --border: #232b4a;
    --ok: #2bb673;
    --warn: #f2c744;
    --crit: #ef4444;
    --info: #38bdf8;
    --unknown: #6b7280;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.45 ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif; }
  header { padding: 16px 20px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); }
  header h1 { margin: 0; font-size: 18px; letter-spacing: 0.2px; }
  header .meta { color: var(--muted); font-size: 12px; }
  main { padding: 20px; display: grid; gap: 20px; max-width: 1400px; margin: 0 auto; }
  .grid { display: grid; gap: 20px; grid-template-columns: 1fr 1fr; }
  @media (max-width: 1024px) { .grid { grid-template-columns: 1fr; } }
  section { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
  section h2 { margin: 0; padding: 12px 16px; font-size: 14px; font-weight: 600; border-bottom: 1px solid var(--border); background: var(--panel-2); display: flex; justify-content: space-between; align-items: center; }
  section h2 .count { color: var(--muted); font-weight: 400; font-size: 12px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--border); vertical-align: top; }
  th { font-weight: 600; color: var(--muted); background: var(--panel-2); position: sticky; top: 0; }
  tr:last-child td { border-bottom: none; }
  .pill { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; }
  .pill.ok      { background: rgba(43,182,115,0.12);  color: var(--ok);      border: 1px solid rgba(43,182,115,0.3); }
  .pill.success { background: rgba(43,182,115,0.12);  color: var(--ok);      border: 1px solid rgba(43,182,115,0.3); }
  .pill.warning { background: rgba(242,199,68,0.12);  color: var(--warn);    border: 1px solid rgba(242,199,68,0.3); }
  .pill.degraded{ background: rgba(242,199,68,0.12);  color: var(--warn);    border: 1px solid rgba(242,199,68,0.3); }
  .pill.failed  { background: rgba(239,68,68,0.12);   color: var(--crit);    border: 1px solid rgba(239,68,68,0.3); }
  .pill.critical{ background: rgba(239,68,68,0.12);   color: var(--crit);    border: 1px solid rgba(239,68,68,0.3); }
  .pill.down    { background: rgba(239,68,68,0.12);   color: var(--crit);    border: 1px solid rgba(239,68,68,0.3); }
  .pill.info    { background: rgba(56,189,248,0.12);  color: var(--info);    border: 1px solid rgba(56,189,248,0.3); }
  .pill.unknown { background: rgba(107,114,128,0.12); color: var(--unknown); border: 1px solid rgba(107,114,128,0.3); }
  .pill.skipped { background: rgba(107,114,128,0.12); color: var(--unknown); border: 1px solid rgba(107,114,128,0.3); }
  .muted { color: var(--muted); }
  .empty { padding: 24px; text-align: center; color: var(--muted); }
  form.inline { display: inline; }
  button.link { background: none; border: none; color: var(--muted); cursor: pointer; font: inherit; padding: 0; }
  button.link:hover { color: var(--text); }
  .login { min-height: 80vh; display: flex; align-items: center; justify-content: center; }
  .login form { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 24px; min-width: 320px; display: grid; gap: 12px; }
  .login h1 { margin: 0 0 8px; font-size: 18px; }
  .login input { background: var(--panel-2); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 10px 12px; font: inherit; }
  .login button { background: var(--info); color: #00131c; border: none; border-radius: 6px; padding: 10px 12px; font: inherit; font-weight: 600; cursor: pointer; }
  .login .err { color: var(--crit); font-size: 13px; }
  .summary-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
  .summary { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; }
  .summary .label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }
  .summary .value { font-size: 22px; font-weight: 600; margin-top: 4px; }
`;

function loginPage(error?: string): string {
  return `<!doctype html><html><head><meta charset="utf-8"><title>Mikrotik Minder</title><meta name="viewport" content="width=device-width,initial-scale=1"><style>${STYLES}</style></head><body><div class="login"><form method="post" action="/login"><h1>Mikrotik Minder</h1><label for="token" class="muted">Admin token</label><input type="password" name="token" id="token" autofocus required>${error ? `<div class="err">${escapeHtml(error)}</div>` : ""}<button type="submit">Sign in</button></form></div></body></html>`;
}

function dashboardPage(data: {
  devices: DeviceRow[];
  jobs: JobRow[];
  alerts: AlertRow[];
  agents: AgentRow[];
  defaultInterval: number;
  defaultGrace: number;
}): string {
  const counts = {
    ok: data.devices.filter((d) => d.last_status === "ok").length,
    degraded: data.devices.filter((d) => d.last_status === "degraded").length,
    down: data.devices.filter((d) => d.last_status === "down").length,
    unknown: data.devices.filter((d) => d.last_status === "unknown").length,
  };

  const deviceRows = data.devices.length
    ? data.devices
        .map((d) => {
          const interval = d.heartbeat_interval_seconds ?? data.defaultInterval;
          const grace = d.grace_seconds ?? data.defaultGrace;
          return `<tr>
            <td><strong>${escapeHtml(d.name)}</strong>${d.site ? ` <span class="muted">· ${escapeHtml(d.site)}</span>` : ""}</td>
            <td><span class="pill ${d.last_status}">${d.last_status}</span></td>
            <td>${relTime(d.last_seen_at)}</td>
            <td class="muted">${escapeHtml(d.role ?? "")}</td>
            <td class="muted">${escapeHtml(d.agent_name)}</td>
            <td class="muted">${interval}s + ${grace}s</td>
          </tr>`;
        })
        .join("")
    : `<tr><td colspan="6" class="empty">No devices yet — register one with POST /v1/admin/devices, then send a heartbeat.</td></tr>`;

  const jobRows = data.jobs.length
    ? data.jobs
        .map(
          (j) => `<tr>
            <td>${escapeHtml(j.kind)}</td>
            <td><span class="pill ${j.status}">${j.status}</span></td>
            <td>${escapeHtml(j.device_name ?? "—")}</td>
            <td>${relTime(j.finished_at)}</td>
            <td class="muted">${j.finished_at - j.started_at}s</td>
            <td class="muted">${escapeHtml((j.summary ?? "").slice(0, 80))}</td>
          </tr>`,
        )
        .join("")
    : `<tr><td colspan="6" class="empty">No jobs reported yet.</td></tr>`;

  const alertRows = data.alerts.length
    ? data.alerts
        .map(
          (a) => `<tr>
            <td><span class="pill ${a.severity}">${a.severity}</span></td>
            <td>${escapeHtml(a.kind)}</td>
            <td>${escapeHtml(a.title)}</td>
            <td>${escapeHtml(a.device_name ?? "—")}</td>
            <td>${relTime(a.created_at)}</td>
          </tr>`,
        )
        .join("")
    : `<tr><td colspan="5" class="empty">No alerts fired yet.</td></tr>`;

  return `<!doctype html><html><head><meta charset="utf-8"><title>Mikrotik Minder</title><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="30"><style>${STYLES}</style></head><body>
    <header>
      <h1>Mikrotik Minder</h1>
      <div class="meta">
        ${data.agents.length} agent${data.agents.length === 1 ? "" : "s"} ·
        ${data.devices.length} device${data.devices.length === 1 ? "" : "s"} ·
        auto-refresh 30s ·
        <form class="inline" method="post" action="/logout"><button class="link" type="submit">sign out</button></form>
      </div>
    </header>
    <main>
      <div class="summary-grid">
        <div class="summary"><div class="label">OK</div><div class="value">${counts.ok}</div></div>
        <div class="summary"><div class="label">Degraded</div><div class="value">${counts.degraded}</div></div>
        <div class="summary"><div class="label">Down</div><div class="value">${counts.down}</div></div>
        <div class="summary"><div class="label">Unknown</div><div class="value">${counts.unknown}</div></div>
      </div>
      <section>
        <h2>Devices <span class="count">${data.devices.length}</span></h2>
        <table><thead><tr><th>Device</th><th>Status</th><th>Last seen</th><th>Role</th><th>Agent</th><th>Interval + grace</th></tr></thead><tbody>${deviceRows}</tbody></table>
      </section>
      <div class="grid">
        <section>
          <h2>Recent jobs <span class="count">${data.jobs.length}</span></h2>
          <table><thead><tr><th>Kind</th><th>Status</th><th>Device</th><th>Finished</th><th>Duration</th><th>Summary</th></tr></thead><tbody>${jobRows}</tbody></table>
        </section>
        <section>
          <h2>Alerts <span class="count">${data.alerts.length}</span></h2>
          <table><thead><tr><th>Severity</th><th>Kind</th><th>Title</th><th>Device</th><th>When</th></tr></thead><tbody>${alertRows}</tbody></table>
        </section>
      </div>
    </main>
  </body></html>`;
}

export default dashboard;
