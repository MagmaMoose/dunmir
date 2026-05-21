export interface Env {
  DB: D1Database;
  ADMIN_TOKEN: string;
  DEFAULT_HEARTBEAT_INTERVAL_SECONDS: string;
  DEFAULT_GRACE_SECONDS: string;
  DASHBOARD_ROWS: string;
}

export type AppVariables = {
  agentId?: string;
  isAdmin?: boolean;
};

export type AppContext = {
  Bindings: Env;
  Variables: AppVariables;
};

export function numEnv(value: string, fallback: number): number {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : fallback;
}
