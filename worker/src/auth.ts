import type { Context, Next } from "hono";
import { type AppContext, DEFAULT_TENANT_ID } from "./env";

const TOKEN_PREFIX = "mtm_";

function base64url(bytes: Uint8Array): string {
  let str = "";
  for (const byte of bytes) str += String.fromCharCode(byte);
  return btoa(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function generateAgentToken(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return TOKEN_PREFIX + base64url(bytes);
}

export async function hashToken(token: string): Promise<string> {
  const data = new TextEncoder().encode(token);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return base64url(new Uint8Array(digest));
}

export function constantTimeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

export function extractBearer(c: Context): string | null {
  const header = c.req.header("authorization");
  if (!header) return null;
  const match = /^Bearer\s+(.+)$/i.exec(header);
  return match ? match[1]!.trim() : null;
}

export function requireAdmin() {
  return async (c: Context<AppContext>, next: Next) => {
    const token = extractBearer(c);
    if (!token || !c.env.ADMIN_TOKEN || !constantTimeEqual(token, c.env.ADMIN_TOKEN)) {
      return c.json({ error: "unauthorized" }, 401);
    }
    c.set("isAdmin", true);
    const tenantId = await resolveTenant(c);
    if (!tenantId) {
      return c.json({ error: "no tenant for this operator" }, 403);
    }
    c.set("tenantId", tenantId);
    await next();
  };
}

/**
 * Cross-tenant superadmin: the admin token PLUS an X-Auth-Email listed in
 * SUPERADMIN_EMAILS. Used for tenant lifecycle (create tenant, manage members),
 * which must NOT be tenant-scoped. With SUPERADMIN_EMAILS unset, nobody is a
 * superadmin (the tenant endpoints are inert) — so single-tenant deploys are
 * unaffected.
 */
export function requireSuperadmin() {
  return async (c: Context<AppContext>, next: Next) => {
    const token = extractBearer(c);
    if (!token || !c.env.ADMIN_TOKEN || !constantTimeEqual(token, c.env.ADMIN_TOKEN)) {
      return c.json({ error: "unauthorized" }, 401);
    }
    const allowed = (c.env.SUPERADMIN_EMAILS ?? "")
      .split(",")
      .map((e) => e.trim().toLowerCase())
      .filter(Boolean);
    const email = (c.req.header("X-Auth-Email") ?? "").trim().toLowerCase();
    if (!email || !allowed.includes(email)) {
      return c.json({ error: "superadmin only" }, 403);
    }
    await next();
  };
}

/**
 * Resolve the tenant an admin request acts on. Single-tenant (the default) →
 * always the default tenant. Multi-tenant → the tenant the authenticated
 * operator email (X-Auth-Email, set by Cloudflare Access) is a member of;
 * an email with no membership gets no tenant (caller returns 403).
 */
export async function resolveTenant(c: Context<AppContext>): Promise<string | null> {
  if (c.env.MULTI_TENANT !== "true") {
    return DEFAULT_TENANT_ID;
  }
  const email = (c.req.header("X-Auth-Email") ?? "").trim().toLowerCase();
  if (!email) return null;
  const row = await c.env.DB.prepare("SELECT tenant_id FROM tenant_members WHERE email = ?1")
    .bind(email)
    .first<{ tenant_id: string }>();
  return row?.tenant_id ?? null;
}

export function requireAgent() {
  return async (c: Context<AppContext>, next: Next) => {
    const token = extractBearer(c);
    if (!token || !token.startsWith(TOKEN_PREFIX)) {
      return c.json({ error: "unauthorized" }, 401);
    }
    const hash = await hashToken(token);
    const row = await c.env.DB.prepare(
      "SELECT id, disabled FROM agents WHERE token_hash = ?1 LIMIT 1",
    )
      .bind(hash)
      .first<{ id: string; disabled: number }>();
    if (!row || row.disabled) {
      return c.json({ error: "unauthorized" }, 401);
    }
    c.set("agentId", row.id);
    await next();
  };
}
