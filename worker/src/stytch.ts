/**
 * Stytch B2B customer authentication for the worker — SaaS Phase 1, §4 of
 * MagmaMoose/mikrotik-minder-pro#24 / #26.
 *
 * Replaces the old "trust the X-Auth-Email header" model. A customer request
 * carries a Stytch **session JWT** (forwarded by the Pro app). The worker
 * validates it LOCALLY against Stytch's JWKS — no Stytch secret at the edge —
 * which cryptographically proves the request is for a specific org + member. The
 * org → local tenant and member → local user are resolved (JIT-linked) from the
 * product tables (migration 0010). Everything fails closed.
 *
 * Cloudflare Access + X-Auth-Email (auth.ts) remain for INTERNAL superadmin only.
 *
 * Config (all NON-secret; set in the deploy env — derive from your project id):
 *   STYTCH_PROJECT_ID — project-live-…           (the JWT audience)
 *   STYTCH_JWKS_URL   — https://api.stytch.com/v1/b2b/sessions/jwks/<project_id>
 *   STYTCH_ISSUER     — stytch.com/<project_id>
 */
import type { Context, Next } from "hono";
import { createRemoteJWKSet, jwtVerify, type JWTPayload } from "jose";
import type { AppContext, Env } from "./env";
import { newId, nowSeconds } from "./ids";

// Cache the remote JWKS per isolate (jose handles key rotation + HTTP caching).
let jwks: ReturnType<typeof createRemoteJWKSet> | null = null;
let jwksFor: string | null = null;

function getJwks(env: Env): ReturnType<typeof createRemoteJWKSet> {
  if (!env.STYTCH_JWKS_URL || !env.STYTCH_ISSUER || !env.STYTCH_PROJECT_ID) {
    throw new Error("Stytch not configured (STYTCH_JWKS_URL / STYTCH_ISSUER / STYTCH_PROJECT_ID)");
  }
  if (!jwks || jwksFor !== env.STYTCH_JWKS_URL) {
    jwks = createRemoteJWKSet(new URL(env.STYTCH_JWKS_URL));
    jwksFor = env.STYTCH_JWKS_URL;
  }
  return jwks;
}

export interface StytchSession {
  memberId: string;
  organizationId: string;
  email: string | null;
}

// Stytch B2B nests session data under this namespaced claim. The signature /
// issuer / audience / expiry checks below are the security guarantee and hold
// regardless of claim shape — this only affects which org/member we resolve, and
// we fail closed when a claim is absent. VERIFY against a real token from your
// project and adjust `pickString` if the shape differs.
const STYTCH_SESSION_CLAIM = "https://stytch.com/session";

/**
 * Validate a Stytch B2B session JWT — RS256 signature against the project JWKS,
 * plus issuer / audience / expiry — and return the member + org. Throws on ANY
 * failure; callers must treat a throw as "unauthenticated".
 */
export async function validateStytchSession(token: string, env: Env): Promise<StytchSession> {
  const { payload } = await jwtVerify(token, getJwks(env), {
    issuer: env.STYTCH_ISSUER,
    audience: env.STYTCH_PROJECT_ID,
    clockTolerance: 30,
    algorithms: ['RS256'],
  });
  const memberId = typeof payload.sub === "string" ? payload.sub : null;
  const organizationId = pickString(payload, "organization_id");
  if (!memberId || !organizationId) {
    throw new Error("Stytch session JWT missing member (sub) or organization_id");
  }
  return { memberId, organizationId, email: pickString(payload, "email_address") };
}

// Look for `key` at the top level of the payload or inside the Stytch session claim.
function pickString(p: JWTPayload, key: string): string | null {
  const top = (p as Record<string, unknown>)[key];
  if (typeof top === "string") return top;
  const claim = (p as Record<string, unknown>)[STYTCH_SESSION_CLAIM];
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
    return { tenantId: tenant.id, userId: existing.user_id };
  }

  // First sight of this member: reuse a user with the same email or create one,
  // then link the Stytch account + tenant membership. All idempotent.
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
