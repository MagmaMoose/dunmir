import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  getAgents,
  getDevices,
  getHealth,
  type Agent,
  type ApiCredentials,
  type Device,
} from "./api";
import { defaultApiBase } from "./config";

const LS_KEYS = {
  baseUrl: "mm.baseUrl",
  token: "mm.token",
  email: "mm.email",
} as const;

function loadLs(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

function saveLs(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* ignore quota / privacy mode errors */
  }
}

type HealthState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ok"; service: string }
  | { kind: "error"; message: string };

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401 || err.status === 403) {
      return `Unauthorized (HTTP ${err.status}). Check your admin token / operator email.`;
    }
    if (err.status === 0) {
      return err.message;
    }
    return `${err.message}${err.body ? `: ${err.body}` : ""}`;
  }
  return err instanceof Error ? err.message : String(err);
}

export function App() {
  const [baseUrl, setBaseUrl] = useState(() =>
    loadLs(LS_KEYS.baseUrl, defaultApiBase()),
  );
  const [token, setToken] = useState(() => loadLs(LS_KEYS.token, ""));
  const [email, setEmail] = useState(() => loadLs(LS_KEYS.email, ""));

  const [health, setHealth] = useState<HealthState>({ kind: "idle" });

  const [agents, setAgents] = useState<Agent[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => saveLs(LS_KEYS.baseUrl, baseUrl), [baseUrl]);
  useEffect(() => saveLs(LS_KEYS.token, token), [token]);
  useEffect(() => saveLs(LS_KEYS.email, email), [email]);

  const checkHealth = useCallback(async () => {
    setHealth({ kind: "loading" });
    try {
      const h = await getHealth(baseUrl);
      setHealth({ kind: "ok", service: h.service });
    } catch (err) {
      setHealth({ kind: "error", message: errorMessage(err) });
    }
  }, [baseUrl]);

  // Check health on first mount.
  useEffect(() => {
    void checkHealth();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    const creds: ApiCredentials = { baseUrl, token, email };
    try {
      const [a, d] = await Promise.all([getAgents(creds), getDevices(creds)]);
      setAgents(a);
      setDevices(d);
    } catch (err) {
      setLoadError(errorMessage(err));
      setAgents([]);
      setDevices([]);
    } finally {
      setLoading(false);
    }
  }, [baseUrl, token, email]);

  return (
    <div className="app">
      <header className="app-header">
        <h1>Mikrotik Minder</h1>
        <span className="subtitle">operator dashboard</span>
      </header>

      <section className="panel">
        <div className="field-grid">
          <label>
            API base URL
            <input
              type="text"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="http://localhost:8000"
              autoComplete="off"
            />
          </label>
          <label>
            Admin token
            <input
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="ADMIN_TOKEN"
              autoComplete="off"
            />
          </label>
          <label>
            Operator email <span className="muted">(optional)</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              autoComplete="off"
            />
          </label>
        </div>

        <div className="actions">
          <button onClick={() => void load()} disabled={loading}>
            {loading ? "Loading…" : "Load"}
          </button>
          <button className="secondary" onClick={() => void checkHealth()}>
            Re-check health
          </button>
          <HealthBadge state={health} />
        </div>

        {loadError && <div className="error">{loadError}</div>}
      </section>

      <section className="panel">
        <h2>
          Agents <span className="count">({agents.length})</span>
        </h2>
        <AgentsTable agents={agents} />
      </section>

      <section className="panel">
        <h2>
          Devices <span className="count">({devices.length})</span>
        </h2>
        <DevicesTable devices={devices} />
      </section>
    </div>
  );
}

function HealthBadge({ state }: { state: HealthState }) {
  switch (state.kind) {
    case "idle":
      return <span className="badge">health: —</span>;
    case "loading":
      return <span className="badge">health: checking…</span>;
    case "ok":
      return (
        <span className="badge badge-ok">health: ok ({state.service})</span>
      );
    case "error":
      return (
        <span className="badge badge-error" title={state.message}>
          health: error
        </span>
      );
  }
}

function fmt(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function AgentsTable({ agents }: { agents: Agent[] }) {
  if (agents.length === 0) {
    return <p className="muted">No agents loaded.</p>;
  }
  return (
    <table>
      <thead>
        <tr>
          <th>ID</th>
          <th>Name</th>
          <th>Created</th>
          <th>Last seen</th>
          <th>Disabled</th>
        </tr>
      </thead>
      <tbody>
        {agents.map((a) => (
          <tr key={a.id}>
            <td className="mono">{fmt(a.id)}</td>
            <td>{fmt(a.name)}</td>
            <td>{fmt(a.created_at)}</td>
            <td>{fmt(a.last_seen_at)}</td>
            <td>{a.disabled ? "yes" : "no"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function DevicesTable({ devices }: { devices: Device[] }) {
  if (devices.length === 0) {
    return <p className="muted">No devices loaded.</p>;
  }
  return (
    <table>
      <thead>
        <tr>
          <th>ID</th>
          <th>Agent</th>
          <th>Name</th>
          <th>Site</th>
          <th>Status</th>
          <th>Last seen</th>
        </tr>
      </thead>
      <tbody>
        {devices.map((d) => (
          <tr key={d.id}>
            <td className="mono">{fmt(d.id)}</td>
            <td className="mono">{fmt(d.agent_id)}</td>
            <td>{fmt(d.name)}</td>
            <td>{fmt(d.site)}</td>
            <td>{fmt(d.last_status)}</td>
            <td>{fmt(d.last_seen_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
