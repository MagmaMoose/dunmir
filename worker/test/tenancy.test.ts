/**
 * Cross-tenant isolation suite — the gate before MULTI_TENANT may be enabled.
 *
 * Runs the REAL worker (its Hono app, requireAdmin, resolveTenant, and the
 * actual SQL in every handler) against an in-memory SQLite seeded with two
 * tenants. A handler that forgot its `tenant_id` filter would let one tenant's
 * resource appear in the other's response — which these assertions catch.
 */
import { beforeEach, describe, expect, it } from "vitest";
import worker from "../src/index";
import { FX, migratedDb, seedTwoTenants, ShimD1 } from "./d1";

const ADMIN_TOKEN = "mtm_test_admin_token";

type CallOpts = { method?: string; email?: string; body?: unknown };

function makeEnv(overrides: Record<string, unknown> = {}) {
  const db = migratedDb();
  seedTwoTenants(db);
  return {
    env: {
      DB: new ShimD1(db),
      ADMIN_TOKEN,
      MULTI_TENANT: "true",
      SUPERADMIN_EMAILS: "root@root.example",
      ...overrides,
    } as unknown as Parameters<typeof worker.fetch>[1],
    db,
  };
}

const ctx = { waitUntil() {}, passThroughOnException() {} } as unknown as ExecutionContext;

function call(env: unknown, path: string, opts: CallOpts = {}): Promise<Response> {
  const headers: Record<string, string> = { authorization: `Bearer ${ADMIN_TOKEN}` };
  if (opts.email) headers["X-Auth-Email"] = opts.email;
  if (opts.body !== undefined) headers["content-type"] = "application/json";
  const req = new Request(`https://minder.test${path}`, {
    method: opts.method ?? "GET",
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  return worker.fetch(req, env as Parameters<typeof worker.fetch>[1], ctx);
}

describe("multi-tenant admin isolation", () => {
  let env: ReturnType<typeof makeEnv>["env"];
  beforeEach(() => {
    env = makeEnv().env;
  });

  it("agents list is scoped to the operator's tenant", async () => {
    const a = await (await call(env, "/v1/admin/agents", { email: FX.emailA })).text();
    expect(a).toContain(FX.nameAgentA);
    expect(a).not.toContain(FX.nameAgentB);

    const b = await (await call(env, "/v1/admin/agents", { email: FX.emailB })).text();
    expect(b).toContain(FX.nameAgentB);
    expect(b).not.toContain(FX.nameAgentA);
  });

  it("devices list is scoped to the operator's tenant", async () => {
    const a = await (await call(env, "/v1/admin/devices", { email: FX.emailA })).text();
    expect(a).toContain(FX.nameDeviceA);
    expect(a).not.toContain(FX.nameDeviceB);
  });

  it("alert routes are scoped to the operator's tenant", async () => {
    const a = await (await call(env, "/v1/admin/alert-routes", { email: FX.emailA })).text();
    expect(a).toContain(FX.nameRouteA);
    expect(a).not.toContain(FX.nameRouteB);
  });

  it("backup listing is scoped — B cannot list A's device backups", async () => {
    const own = await call(env, `/v1/admin/devices/${FX.deviceA}/backups`, { email: FX.emailA });
    expect(await own.text()).toContain(FX.fileA);

    const cross = await call(env, `/v1/admin/devices/${FX.deviceA}/backups`, { email: FX.emailB });
    expect(cross.status).toBe(200);
    expect(await cross.text()).not.toContain(FX.fileA); // empty — A's device isn't in B's tenant
  });

  it("enqueue against another tenant's device is 404 (no command created)", async () => {
    const cross = await call(env, "/v1/admin/commands", {
      method: "POST",
      email: FX.emailA,
      body: { device_id: FX.deviceB, kind: "backup" },
    });
    expect(cross.status).toBe(404);

    const own = await call(env, "/v1/admin/commands", {
      method: "POST",
      email: FX.emailA,
      body: { device_id: FX.deviceA, kind: "backup" },
    });
    expect(own.status).toBe(201);
  });

  it("sensitive-export artifact cannot be read across tenants", async () => {
    // A tries to read B's artifact → 404, and B's secret is never returned.
    const cross = await call(env, `/v1/admin/commands/${FX.cmdB}/artifact`, { email: FX.emailA });
    expect(cross.status).toBe(404);
    expect(await cross.text()).not.toContain(FX.artifactB);

    // A's own command passes the tenant gate (NOT 404/403). We don't assert the
    // body here: the purge query returns it via a self-referencing CTE whose
    // materialization differs across SQLite versions — orthogonal to isolation.
    const own = await call(env, `/v1/admin/commands/${FX.cmdA}/artifact`, { email: FX.emailA });
    expect(own.status).not.toBe(404);
    expect(own.status).not.toBe(403);
  });

  it("backup download is refused across tenants before any storage access", async () => {
    // 404 (not 410/500): the tenant filter rejects it before the R2 lookup,
    // which is why this test needs no R2 binding.
    const cross = await call(env, `/v1/admin/backups/${FX.backupB}/download`, { email: FX.emailA });
    expect(cross.status).toBe(404);
  });

  it("an operator with no tenant membership is denied (403)", async () => {
    const res = await call(env, "/v1/admin/agents", { email: "ghost@nowhere.example" });
    expect(res.status).toBe(403);
  });
});

describe("superadmin gating", () => {
  it("tenant lifecycle requires a SUPERADMIN_EMAILS member", async () => {
    const { env } = makeEnv();
    const denied = await call(env, "/v1/superadmin/tenants", {
      method: "POST",
      email: FX.emailA, // a normal operator, not a superadmin
      body: { name: "Sneaky" },
    });
    expect(denied.status).toBe(403);

    const ok = await call(env, "/v1/superadmin/tenants", {
      method: "POST",
      email: "root@root.example",
      body: { name: "Legit" },
    });
    expect(ok.ok).toBe(true);
  });
});

describe("single-tenant inertness (MULTI_TENANT off)", () => {
  it("resolves tnt_default without any Access email and ignores other tenants", async () => {
    const { env } = makeEnv({ MULTI_TENANT: "false" });
    const res = await call(env, "/v1/admin/agents"); // no X-Auth-Email at all
    expect(res.status).toBe(200);
    const text = await res.text();
    expect(text).toContain("agent-DEFAULT");
    expect(text).not.toContain(FX.nameAgentA);
    expect(text).not.toContain(FX.nameAgentB);
  });
});
