/**
 * Stytch B2B customer authentication for the worker — SaaS Phase 1, §4 of
 * MagmaMoose/mikrotik-minder-pro#24 / #26.
 *
 * Replaces the old "trust the X-Auth-Email header" model. A customer request
 * carries a Stytch **session JWT** (forwarded by the Pro app). The worker
 * validates it LOCALLY against the project JWKS using **Web Crypto** — no
 * dependency, no Stytch secret at the edge — which cryptographically proves the
 * request is for a specific org + member. The org → local tenant and member →
 * local user are resolved (JIT-linked) from the product tables (migration 0010).
 * Everything fails closed.
 *
 * Cloudflare Access + X-Auth-Email (auth.ts) remain for INTERNAL superadmin only.
 *
 * Config (all NON-secret; per Stytch, derive from your project id + environment):
 *   STYTCH_PROJECT_ID — project-live-…                          (the JWT audience)
 *   STYTCH_JWKS_URL   — https://live.stytch.com/v1/sessions/jwks/<project_id>
 *                       (use test.stytch.com for a test project)
 *   STYTCH_ISSUER     — stytch.com/<project_id>
 */
import type { Context, Next } from "hono";
import type { AppContext, Env } from "./env";
import { newId, nowSeconds } from "./ids";

const CLOCK_SKEW_SECONDS = 30;
const JWKS_TTL_MS = 10 * 60 * 1000;

// Per-isolate JWKS cache: kid → imported RSA public key.
let jwksCache: { url: string; at: number; keys: Map<string, CryptoKey> } | null = null;

function b64urlToBytes(s: string): Uint8Array {
  const pad = s.length % 4 === 0 ? "" : "=".repeat(4 - (s.length % 4));
  const bin = atob(s.replace(/-/g, "+").replace(/_/g, "/") + pad);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function b64urlToJson<T>(s: string): T {
  return JSON.parse(new TextDecoder().decode(b64urlToBytes(s))) as T;
}

interface Jwk {
  kid?: string;
  kty?: string;
  n?: string;
  e?: string;
}

// Fetch + import the project JWKS (cached per isolate with a short TTL). Keys are
// imported as RSASSA-PKCS1-v1_5 / SHA-256 (RS256) — the only algorithm Stytch signs
// with, and the only one these keys can ever verify, so alg is hard-pinned here.
async function loadJwks(env: Env): Promise<Map<string, CryptoKey>> {
  if (!env.STYTCH_JWKS_URL) throw new Error("STYTCH_JWKS_URL not configured");
  if (jwksCache && jwksCache.url === env.STYTCH_JWKS_URL && Date.now() - jwksCache.at < JWKS_TTL_MS) {
    return jwksCache.keys;
  }
  const res = await fetch(env.STYTCH_JWKS_URL, { headers: { accept: "application/json" } });
  if (!res.ok) throw new Error(`JWKS fetch failed (HTTP ${res.status})`);
  const body = (await res.json()) as { keys?: Jwk[] };
  const keys = new Map<string, CryptoKey>();
  for (const jwk of body.keys ?? []) {
    if (jwk.kty !== "RSA" || !jwk.kid || !jwk.n || !jwk.e) continue;
    keys.set(
      jwk.kid,
      await crypto.subtle.importKey(
        "jwk",
        { kty: "RSA", n: jwk.n, e: jwk.e, alg: "RS256", ext: true },
        { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
        false,
        ["verify"],
      ),
    );
  }
  jwksCache = { url: env.STYTCH_JWKS_URL, at: Date.now(), keys };
  return keys;
}

export interface StytchSession {
  memberId: string;
  organizationId: string;
  email: string | null;
}

interface JwtHeader {
  alg?: string;
  kid?: string;
}
type JwtPayload = Record<string, unknown>;

/**
 * Validate a Stytch B2B session JWT — RS256 signature against the project JWKS,
 * plus issuer / audience / expiry — with Web Crypto. Throws on ANY failure;
 * callers must treat a throw as "unauthenticated".
 */
export async function validateStytchSession(token: string, env: Env): Promise<StytchSession> {
  const parts = token.split(".");
  if (parts.length !== 3) throw new Error("malformed JWT");
  const [headerB64, payloadB64, sigB64] = parts as [string, string, string];

  const header = b64urlToJson<JwtHeader>(headerB64);
  if (header.alg !== "RS256" || !header.kid) throw new Error("unexpected JWT header"); // pin alg

  const key = (await loadJwks(env)).get(header.kid);
  if (!key) throw new Error("unknown signing key (kid)");

  const valid = await crypto.subtle.verify(
    "RSASSA-PKCS1-v1_5",
    key,
    b64urlToBytes(sigB64),
    new TextEncoder().encode(`${headerB64}.${payloadB64}`),
  );
  if (!valid) throw new Error("bad signature");

  const payload = b64urlToJson<JwtPayload>(payloadB64);
  const now = nowSeconds();
  if (typeof payload.exp === "number" && now > payload.exp + CLOCK_SKEW_SECONDS) {
    throw new Error("session expired");
  }
  if (typeof payload.nbf === "number" && now < payload.nbf - CLOCK_SKEW_SECONDS) {
    throw new Error("session not yet valid");
  }
  if (env.STYTCH_ISSUER && payload.iss !== env.STYTCH_ISSUER) {
    throw new Error("bad issuer");
  }
  if (env.STYTCH_PROJECT_ID && !audienceMatches(payload.aud, env.STYTCH_PROJECT_ID)) {
    throw new Error("bad audience");
  }

  const memberId = typeof payload.sub === "string" ? payload.sub : null;
  const organizationId = pickString(payload, "organization_id");
  if (!memberId || !organizationId) {
    throw new Error("session missing member (sub) or organization_id");
  }
  return { memberId, organizationId, email: pickString(payload, "email_address") };
}

function audienceMatches(aud: unknown, projectId: string): boolean {
  return aud === projectId || (Array.isArray(aud) && aud.includes(projectId));
}

// Stytch B2B nests session data under this namespaced claim. The signature /
// issuer / audience / expiry checks above are the security guarantee and hold
// regardless of claim shape — this only affects which org/member we resolve, and
// we fail closed when a claim is absent. VERIFY against a real token from your
// project and adjust `pickString` if the shape differs.
const STYTCH_SESSION_CLAIM = "https://stytch.com/session";

function pickString(p: JwtPayload, key: string): string | null {
  const top = p[key];
  if (typeof top === "string") return top;
  const claim = p[STYTCH_SESSION_CLAIM];
  if (claim && typeof claim === "object") {
    const v = (claim as Record<string, unknown>)[key];
    if (typeof v === "string") return v;
  }
  return null;
}

/**
 * Hono middleware: authenticate a customer request by its forwarded Stytch
 * session JWT (`Authorization: Bearer …`), resolve the local tenant + user, and
 * scope the request (sets `tenantId` + `userId`). Fails closed.
 */
export function requireCustomer() {
  return async (c: Context<AppContext>, next: Next) => {
    const header = c.req.header("authorization");
    const match = header ? /^Bearer\s+(.+)$/i.exec(header) : null;
    if (!match) return c.json({ error: "unauthorized" }, 401);

    let session: StytchSession;
    try {
      session = await validateStytchSession(match[1]!.trim(), c.env);
    } catch {
      return c.json({ error: "unauthorized" }, 401);
    }

    const resolved = await resolveCustomer(c.env, session);
    if (!resolved) return c.json({ error: "organization is not provisioned" }, 403);

    c.set("tenantId", resolved.tenantId);
    c.set("userId", resolved.userId);
    await next();
  };
}

/**
 * Map a validated Stytch session → local tenant + user, JIT-linking the member
 * to a local user + membership on first sight. The org→tenant link MUST already
 * exist (created during onboarding, Phase 2) — an unknown org is refused here,
 * never auto-provisioned, so a stray valid session can't mint itself a tenant.
 */
async function resolveCustomer(
  env: Env,
  s: StytchSession,
): Promise<{ tenantId: string; userId: string } | null> {
  const tenant = await env.DB.prepare(
    "SELECT id FROM tenants WHERE stytch_org_id = ?1 AND deleted_at IS NULL",
  )
    .bind(s.organizationId)
    .first<{ id: string }>();
  if (!tenant) return null;

  const existing = await env.DB.prepare(
    "SELECT user_id FROM auth_accounts WHERE provider = 'stytch' AND provider_user_id = ?1",
  )
    .bind(s.memberId)
    .first<{ user_id: string }>();

  const now = nowSeconds();
  if (existing) {
    await env.DB.prepare("UPDATE users SET last_seen_at = ?1 WHERE id = ?2")
      .bind(now, existing.user_id)
      .run();
    // Ensure tenant membership exists for this user (idempotent).
    await env.DB.prepare(
      `INSERT OR IGNORE INTO tenant_memberships (tenant_id, user_id, role, created_at)
         VALUES (?1, ?2, 'member', ?3)`,
    )
      .bind(tenant.id, existing.user_id, now)
      .run();
    return { tenantId: tenant.id, userId: existing.user_id };
  }

  // First sight of this member: reuse a user with the same (normalized) email or
  // create one, then link the Stytch account + tenant membership. All idempotent.
  const email = s.email?.trim().toLowerCase() ?? `${s.memberId}@members.stytch`;
  await env.DB.prepare(
    `INSERT INTO users (id, primary_email, created_at, last_seen_at) VALUES (?1, ?2, ?3, ?3)
       ON CONFLICT(primary_email) DO UPDATE SET last_seen_at = ?3`,
  )
    .bind(newId("usr"), email, now)
    .run();
  const user = await env.DB.prepare("SELECT id FROM users WHERE primary_email = ?1")
    .bind(email)
    .first<{ id: string }>();
  if (!user) return null;

  await env.DB.prepare(
    `INSERT OR IGNORE INTO auth_accounts (provider, provider_user_id, user_id, created_at)
       VALUES ('stytch', ?1, ?2, ?3)`,
  )
    .bind(s.memberId, user.id, now)
    .run();
  await env.DB.prepare(
    `INSERT OR IGNORE INTO tenant_memberships (tenant_id, user_id, role, created_at)
       VALUES (?1, ?2, 'member', ?3)`,
  )
    .bind(tenant.id, user.id, now)
    .run();

  return { tenantId: tenant.id, userId: user.id };
}
