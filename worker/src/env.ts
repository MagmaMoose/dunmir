export interface Env {
  DB: D1Database;
  // R2 bucket holding encrypted device backups. Bodies are AES-encrypted by
  // RouterOS before they ever leave the device — the worker only ever sees
  // ciphertext and re-streams it on download.
  BACKUPS: R2Bucket;
  ADMIN_TOKEN: string;
  DEFAULT_HEARTBEAT_INTERVAL_SECONDS: string;
  DEFAULT_GRACE_SECONDS: string;
  // Optional Slack integration. When SLACK_BOT_TOKEN is set, every alert is
  // also posted to Slack via chat.postMessage. The channel is chosen by alert
  // kind: wins → SUCCESS, config changes → INFO, everything else → FAILURE.
  // INFO falls back to FAILURE when unset; an unset target channel = skip.
  SLACK_BOT_TOKEN?: string;
  SLACK_SUCCESS_CHANNEL?: string;
  SLACK_FAILURE_CHANNEL?: string;
  SLACK_INFO_CHANNEL?: string;
  // Optional. Public base URL of the Pro UI (no trailing slash). Used to build
  // deep links in Slack alert bodies (Download buttons, etc.).
  PRO_UI_URL?: string;
}

export type AppVariables = {
  agentId?: string;
  isAdmin?: boolean;
};

export type AppContext = {
  Bindings: Env;
  Variables: AppVariables;
};

/**
 * Parse a numeric env var, falling back when it isn't a finite integer ≥ `min`.
 *
 * `min` defaults to 1 so that callers expressing intervals (which must be > 0)
 * stay safe, but callers that want to allow 0 — e.g. "no grace period", or
 * "empty dashboard" — pass `min = 0` explicitly. Anything below `min` falls
 * back; the env var is treated as malformed rather than silently accepted.
 */
export function numEnv(value: string, fallback: number, min: number = 1): number {
  const n = Number(value);
  return Number.isFinite(n) && Number.isInteger(n) && n >= min ? n : fallback;
}
