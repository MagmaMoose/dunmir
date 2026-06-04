declare global {
  interface Window {
    __CONFIG__?: {
      API_BASE?: string;
    };
  }
}

const DEFAULT_API_BASE = "http://localhost:8000";

/**
 * Resolve the default API base URL.
 *
 * Precedence:
 *   1. Runtime config injected via window.__CONFIG__.API_BASE (Docker /config.js)
 *   2. Build-time Vite env VITE_API_BASE
 *   3. Hard-coded default (http://localhost:8000)
 *
 * Note: the user can still override this in the UI; the override is persisted
 * to localStorage. This function only provides the initial default.
 */
export function defaultApiBase(): string {
  const runtime = window.__CONFIG__?.API_BASE;
  if (runtime && runtime.trim() !== "") {
    return runtime.trim();
  }
  const buildTime = import.meta.env.VITE_API_BASE as string | undefined;
  if (buildTime && buildTime.trim() !== "") {
    return buildTime.trim();
  }
  return DEFAULT_API_BASE;
}

export {};
