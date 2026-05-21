import type { Context, Next } from "hono";
import type { AppContext } from "./env";

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
    await next();
  };
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
