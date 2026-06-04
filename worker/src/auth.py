"""Authentication + tenant scoping (port of auth.ts).

Three identities:
  * agents — ``mtm_…`` bearer tokens (hashed in D1) → :func:`require_agent`.
  * operators — a Stytch customer session JWT **or** the shared admin token →
    :func:`require_operator`.
  * superadmins — admin token + an ``X-Auth-Email`` in ``SUPERADMIN_EMAILS`` →
    :func:`require_superadmin`.

Each is a FastAPI dependency: it returns the authenticated scope (agent id, or an
:class:`OperatorAuth`) and raises :class:`fastapi.HTTPException` on failure.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass

from fastapi import Depends, Request

from deps import get_env
from env import DEFAULT_TENANT_ID, Env
from errors import http_error
from ids import now_seconds
from stytch import customer_from_bearer

TOKEN_PREFIX = "mtm_"
_BEARER_RE = re.compile(r"^Bearer\s+(.+)$", re.IGNORECASE)


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def generate_agent_token() -> str:
    return TOKEN_PREFIX + _base64url(secrets.token_bytes(32))


def hash_token(token: str) -> str:
    return _base64url(hashlib.sha256(token.encode()).digest())


def constant_time_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def extract_bearer(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if not header:
        return None
    match = _BEARER_RE.match(header)
    return match.group(1).strip() if match else None


@dataclass
class OperatorAuth:
    """Authenticated operator scope set by :func:`require_operator` / admin."""

    tenant_id: str
    user_id: str | None = None
    is_admin: bool = False


async def resolve_tenant(request: Request, env: Env) -> str | None:
    """The tenant an admin request acts on.

    Single-tenant (default) → always the default tenant. Multi-tenant → the tenant
    the authenticated operator email (``X-Auth-Email``, set by Cloudflare Access) is
    a member of; an email with no membership gets no tenant (caller returns 403).
    """
    if env.get("MULTI_TENANT") != "true":
        return DEFAULT_TENANT_ID
    email = (request.headers.get("X-Auth-Email") or "").strip().lower()
    if not email:
        return None
    row = await env.db.prepare("SELECT tenant_id FROM tenant_members WHERE email = ?1").bind(email).first()
    return row["tenant_id"] if row else None


async def require_admin(request: Request, env: Env = Depends(get_env)) -> OperatorAuth:
    """Admin-token-only auth (tenant-scoped via ``X-Auth-Email``)."""
    token = extract_bearer(request)
    admin_token = env.get("ADMIN_TOKEN")
    if not token or not admin_token or not constant_time_equal(token, admin_token):
        raise http_error(401, "unauthorized")
    tenant_id = await resolve_tenant(request, env)
    if not tenant_id:
        raise http_error(403, "no tenant for this operator")
    return OperatorAuth(tenant_id=tenant_id, is_admin=True)


async def require_operator(request: Request, env: Env = Depends(get_env)) -> OperatorAuth:
    """Operator auth for the customer-facing admin API.

    A customer **Stytch session** (validated locally against the project JWKS →
    tenant + user) OR the shared **admin token** (superadmin / internal / pre-cutover
    Pro, scoped via ``X-Auth-Email``). The Stytch session is tried first; a
    JWT-shaped bearer that fails validation is rejected and never falls through to
    the admin token. With ``STYTCH_JWKS_URL`` unset this is exactly ``require_admin``.
    """
    token = extract_bearer(request)
    if not token:
        raise http_error(401, "unauthorized")

    # A Stytch session JWT has three dot-separated segments. When Stytch is
    # configured, a JWT-shaped bearer is treated as a customer session.
    if env.get("STYTCH_JWKS_URL") and len(token.split(".")) == 3:
        auth = await customer_from_bearer(token, env)
        if auth.ok:
            return OperatorAuth(tenant_id=auth.tenant_id, user_id=auth.user_id)
        # Valid session whose org isn't a tenant yet → 403; anything else → 401.
        if auth.reason == "no-tenant":
            raise http_error(403, "organization is not provisioned")
        raise http_error(401, "unauthorized")

    # Otherwise: the shared admin token (superadmin / internal / pre-cutover Pro).
    admin_token = env.get("ADMIN_TOKEN")
    if not admin_token or not constant_time_equal(token, admin_token):
        raise http_error(401, "unauthorized")
    tenant_id = await resolve_tenant(request, env)
    if not tenant_id:
        raise http_error(403, "no tenant for this operator")
    return OperatorAuth(tenant_id=tenant_id, is_admin=True)


async def require_superadmin(request: Request, env: Env = Depends(get_env)) -> str:
    """Cross-tenant superadmin: admin token PLUS an ``X-Auth-Email`` in
    ``SUPERADMIN_EMAILS``. With ``SUPERADMIN_EMAILS`` unset, nobody is a superadmin
    (the tenant endpoints are inert). Returns the authenticated email.
    """
    token = extract_bearer(request)
    admin_token = env.get("ADMIN_TOKEN")
    if not token or not admin_token or not constant_time_equal(token, admin_token):
        raise http_error(401, "unauthorized")
    allowed = [e.strip().lower() for e in (env.get("SUPERADMIN_EMAILS") or "").split(",") if e.strip()]
    email = (request.headers.get("X-Auth-Email") or "").strip().lower()
    if not email or email not in allowed:
        raise http_error(403, "superadmin only")
    return email


async def require_agent(request: Request, env: Env = Depends(get_env)) -> str:
    """Authenticate an agent by its ``mtm_…`` bearer token; returns the agent id.

    Any authenticated agent contact marks the agent seen (throttled to ~once/min)
    and records its Cloudflare-observed egress IP.
    """
    token = extract_bearer(request)
    if not token or not token.startswith(TOKEN_PREFIX):
        raise http_error(401, "unauthorized")
    token_hash = hash_token(token)
    row = await env.db.prepare(
        "SELECT id, disabled, last_seen_at FROM agents WHERE token_hash = ?1 LIMIT 1"
    ).bind(token_hash).first()
    if not row or row["disabled"]:
        raise http_error(401, "unauthorized")
    agent_id = row["id"]
    now = now_seconds()
    last_seen = row["last_seen_at"]
    if not last_seen or now - last_seen >= 60:
        ip = request.headers.get("cf-connecting-ip")
        await env.db.prepare("UPDATE agents SET last_seen_at = ?1, last_ip = ?2 WHERE id = ?3").bind(
            now, ip, agent_id
        ).run()
    return agent_id
