export interface HealthResponse {
  ok: boolean;
  service: string;
}

export interface Agent {
  id: string;
  name: string;
  created_at?: string | null;
  last_seen_at?: string | null;
  disabled?: boolean;
  [key: string]: unknown;
}

export interface Device {
  id: string;
  agent_id?: string;
  name: string;
  site?: string | null;
  last_status?: string | null;
  last_seen_at?: string | null;
  [key: string]: unknown;
}

export interface AgentsResponse {
  agents: Agent[];
}

export interface DevicesResponse {
  devices: Device[];
}

export interface ApiCredentials {
  /** Base URL of the control plane, e.g. http://localhost:8000 (no trailing slash). */
  baseUrl: string;
  /** Admin bearer token. */
  token: string;
  /** Optional operator email, sent as X-Auth-Email in multi-tenant mode. */
  email?: string;
}

export class ApiError extends Error {
  status: number;
  body?: string;

  constructor(message: string, status: number, body?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

function normalizeBase(baseUrl: string): string {
  return baseUrl.replace(/\/+$/, "");
}

function authHeaders(creds: ApiCredentials): Record<string, string> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${creds.token}`,
    Accept: "application/json",
  };
  if (creds.email && creds.email.trim() !== "") {
    headers["X-Auth-Email"] = creds.email.trim();
  }
  return headers;
}

async function request<T>(
  url: string,
  init: RequestInit,
): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(url, init);
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    throw new ApiError(`Network error: ${detail}`, 0);
  }

  if (!resp.ok) {
    let body: string | undefined;
    try {
      body = await resp.text();
    } catch {
      body = undefined;
    }
    throw new ApiError(
      `Request to ${url} failed with HTTP ${resp.status}`,
      resp.status,
      body,
    );
  }

  return (await resp.json()) as T;
}

/** GET /v1/health — no auth required. */
export async function getHealth(baseUrl: string): Promise<HealthResponse> {
  const base = normalizeBase(baseUrl);
  return request<HealthResponse>(`${base}/v1/health`, {
    method: "GET",
    headers: { Accept: "application/json" },
  });
}

/** GET /v1/admin/agents — requires admin auth. */
export async function getAgents(creds: ApiCredentials): Promise<Agent[]> {
  const base = normalizeBase(creds.baseUrl);
  const data = await request<AgentsResponse>(`${base}/v1/admin/agents`, {
    method: "GET",
    headers: authHeaders(creds),
  });
  return data.agents ?? [];
}

/** GET /v1/admin/devices — requires admin auth. */
export async function getDevices(creds: ApiCredentials): Promise<Device[]> {
  const base = normalizeBase(creds.baseUrl);
  const data = await request<DevicesResponse>(`${base}/v1/admin/devices`, {
    method: "GET",
    headers: authHeaders(creds),
  });
  return data.devices ?? [];
}
