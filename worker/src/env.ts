export interface Env {
  DB: D1Database;
  ADMIN_TOKEN: string;
  DEFAULT_HEARTBEAT_INTERVAL_SECONDS: string;
  DEFAULT_GRACE_SECONDS: string;
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
