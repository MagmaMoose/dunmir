"""Stytch B2B customer authentication (port of stytch.ts).

A customer request carries a Stytch **session JWT** (forwarded by the Pro app).
It is validated LOCALLY against the project JWKS (RS256 signature + issuer /
audience / expiry) using the Workers runtime's Web Crypto — no Stytch secret at
the edge. The org → local tenant and member → local user are JIT-linked from the
product tables. Everything fails closed.

The crypto primitives (:func:`_load_jwks` + :func:`_verify_rs256`) are the only
parts that touch the Workers runtime; tests monkeypatch them with a ``cryptography``
implementation so the orchestration + claim handling are exercised directly.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any

from ids import new_id, now_seconds

CLOCK_SKEW_SECONDS = 30
JWKS_TTL_MS = 10 * 60 * 1000

STYTCH_SESSION_CLAIM = "https://stytch.com/session"
STYTCH_ORG_CLAIM = "https://stytch.com/organization"

# Per-process JWKS cache: {"url", "at" (ms), "keys": {kid: imported key}}.
_jwks_cache: dict[str, Any] | None = None


def _b64url_to_bytes(s: str) -> bytes:
    pad = "" if len(s) % 4 == 0 else "=" * (4 - (len(s) % 4))
    return base64.urlsafe_b64decode(s + pad)


def _b64url_to_json(s: str) -> Any:
    return json.loads(_b64url_to_bytes(s).decode())


@dataclass
class StytchSession:
    member_id: str
    organization_id: str
    email: str | None


# --- Crypto primitives (Workers Web Crypto; monkeypatched in tests) ----------


def _on_workers() -> bool:
    try:
        import js  # noqa: F401

        return True
    except ImportError:
        return False


async def _load_jwks(env) -> dict[str, Any]:
    """Fetch + import the project JWKS, cached per process with a short TTL.

    Keys are imported as RSASSA-PKCS1-v1_5 / SHA-256 (RS256) — the only algorithm
    Stytch signs with — so the algorithm is hard-pinned. The import uses Web Crypto
    on Workers and ``cryptography`` when running as an ordinary process.
    """
    global _jwks_cache
    jwks_url = env.get("STYTCH_JWKS_URL")
    if not jwks_url:
        raise ValueError("STYTCH_JWKS_URL not configured")
    now_ms = time.time() * 1000
    if _jwks_cache and _jwks_cache["url"] == jwks_url and now_ms - _jwks_cache["at"] < JWKS_TTL_MS:
        return _jwks_cache["keys"]

    import outbound

    res = await outbound.fetch(jwks_url, headers={"accept": "application/json"})
    if not res.ok:
        raise ValueError(f"JWKS fetch failed (HTTP {res.status})")
    body = await res.json()
    keys: dict[str, Any] = {}
    for jwk in body.get("keys", []) or []:
        if jwk.get("kty") != "RSA" or not jwk.get("kid") or not jwk.get("n") or not jwk.get("e"):
            continue
        keys[jwk["kid"]] = await _import_rsa_key(jwk["n"], jwk["e"])
    _jwks_cache = {"url": jwks_url, "at": now_ms, "keys": keys}
    return keys


async def _import_rsa_key(n: str, e: str) -> Any:
    if _on_workers():
        import js
        from pyodide.ffi import to_js

        jwk_js = to_js(
            {"kty": "RSA", "n": n, "e": e, "alg": "RS256", "ext": True},
            dict_converter=js.Object.fromEntries,
        )
        algo = to_js({"name": "RSASSA-PKCS1-v1_5", "hash": "SHA-256"}, dict_converter=js.Object.fromEntries)
        usages = js.Array.new()
        usages.push("verify")
        return await js.crypto.subtle.importKey("jwk", jwk_js, algo, False, usages)

    from cryptography.hazmat.primitives.asymmetric import rsa

    n_int = int.from_bytes(_b64url_to_bytes(n), "big")
    e_int = int.from_bytes(_b64url_to_bytes(e), "big")
    return rsa.RSAPublicNumbers(e_int, n_int).public_key()


async def _verify_rs256(key: Any, signing_input: bytes, signature: bytes) -> bool:
    if _on_workers():
        import js
        from pyodide.ffi import to_js

        return bool(
            await js.crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, to_js(signature), to_js(signing_input))
        )

    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    try:
        key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
        return True
    except InvalidSignature:
        return False


# --- Validation + claim handling (pure) --------------------------------------


def _audience_matches(aud: Any, project_id: str) -> bool:
    return aud == project_id or (isinstance(aud, list) and project_id in aud)


def _claim_object(payload: dict, ns: str) -> dict | None:
    c = payload.get(ns)
    return c if isinstance(c, dict) else None


def _pick_string(payload: dict, key: str) -> str | None:
    top = payload.get(key)
    if isinstance(top, str):
        return top
    for ns in (STYTCH_ORG_CLAIM, STYTCH_SESSION_CLAIM):
        obj = _claim_object(payload, ns)
        if obj is not None:
            v = obj.get(key)
            if isinstance(v, str):
                return v
    return None


def _pick_email(payload: dict) -> str | None:
    direct = _pick_string(payload, "email_address")
    if direct:
        return direct
    session = _claim_object(payload, STYTCH_SESSION_CLAIM)
    factors = session.get("authentication_factors") if session else None
    if isinstance(factors, list):
        for f in factors:
            ef = f.get("email_factor") if isinstance(f, dict) else None
            addr = ef.get("email_address") if isinstance(ef, dict) else None
            if isinstance(addr, str):
                return addr
    return None


async def validate_stytch_session(token: str, env) -> StytchSession:
    """Validate a Stytch B2B session JWT. Raises on ANY failure."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("malformed JWT")
    header_b64, payload_b64, sig_b64 = parts

    header = _b64url_to_json(header_b64)
    if header.get("alg") != "RS256" or not header.get("kid"):
        raise ValueError("unexpected JWT header")  # pin alg

    keys = await _load_jwks(env)
    key = keys.get(header["kid"])
    if key is None:
        raise ValueError("unknown signing key (kid)")

    signing_input = f"{header_b64}.{payload_b64}".encode()
    if not await _verify_rs256(key, signing_input, _b64url_to_bytes(sig_b64)):
        raise ValueError("bad signature")

    payload = _b64url_to_json(payload_b64)
    now = now_seconds()
    exp = payload.get("exp")
    if isinstance(exp, (int, float)) and now > exp + CLOCK_SKEW_SECONDS:
        raise ValueError("session expired")
    nbf = payload.get("nbf")
    if isinstance(nbf, (int, float)) and now < nbf - CLOCK_SKEW_SECONDS:
        raise ValueError("session not yet valid")
    issuer = env.get("STYTCH_ISSUER")
    if issuer and payload.get("iss") != issuer:
        raise ValueError("bad issuer")
    project_id = env.get("STYTCH_PROJECT_ID")
    if project_id and not _audience_matches(payload.get("aud"), project_id):
        raise ValueError("bad audience")

    member_id = payload.get("sub") if isinstance(payload.get("sub"), str) else None
    organization_id = _pick_string(payload, "organization_id")
    if not member_id or not organization_id:
        raise ValueError("session missing member (sub) or organization_id")
    return StytchSession(member_id=member_id, organization_id=organization_id, email=_pick_email(payload))


@dataclass
class CustomerAuth:
    ok: bool
    tenant_id: str | None = None
    user_id: str | None = None
    reason: str | None = None  # "invalid" | "no-tenant"


async def customer_from_bearer(token: str, env) -> CustomerAuth:
    """Authenticate a bearer as a Stytch session and resolve tenant + user.

    Never raises. ``invalid`` → not a valid session (→ 401); ``no-tenant`` → a valid
    session whose org has no provisioned tenant (→ 403).
    """
    try:
        session = await validate_stytch_session(token, env)
    except Exception:
        return CustomerAuth(ok=False, reason="invalid")
    resolved = await resolve_customer(env, session)
    if resolved is None:
        return CustomerAuth(ok=False, reason="no-tenant")
    return CustomerAuth(ok=True, tenant_id=resolved["tenant_id"], user_id=resolved["user_id"])


async def resolve_customer(env, s: StytchSession) -> dict | None:
    """Map a validated session → local tenant + user, JIT-linking on first sight.

    An org with no local tenant is provisioned one here (self-serve signup); the
    member who first touches it becomes its owner.
    """
    db = env.db
    now = now_seconds()
    tenant = await db.prepare(
        "SELECT id FROM tenants WHERE stytch_org_id = ?1 AND deleted_at IS NULL"
    ).bind(s.organization_id).first()

    new_tenant = False
    if not tenant:
        await db.prepare(
            "INSERT OR IGNORE INTO tenants (id, name, stytch_org_id, created_at) VALUES (?1, ?2, ?3, ?4)"
        ).bind(new_id("tnt"), s.organization_id, s.organization_id, now).run()
        tenant = await db.prepare(
            "SELECT id FROM tenants WHERE stytch_org_id = ?1 AND deleted_at IS NULL"
        ).bind(s.organization_id).first()
        if not tenant:
            return None
        new_tenant = True

    existing = await db.prepare(
        "SELECT user_id FROM auth_accounts WHERE provider = 'stytch' AND provider_user_id = ?1"
    ).bind(s.member_id).first()

    if existing:
        await db.prepare("UPDATE users SET last_seen_at = ?1 WHERE id = ?2").bind(now, existing["user_id"]).run()
        await db.prepare(
            "INSERT OR IGNORE INTO tenant_memberships (tenant_id, user_id, role, created_at) "
            "VALUES (?1, ?2, 'member', ?3)"
        ).bind(tenant["id"], existing["user_id"], now).run()
        return {"tenant_id": tenant["id"], "user_id": existing["user_id"]}

    # First sight of this member: reuse a user with the same (normalized) email or
    # create one, then link the Stytch account + tenant membership. All idempotent.
    email = (s.email or "").strip().lower() or f"{s.member_id}@members.stytch"
    await db.prepare(
        "INSERT INTO users (id, primary_email, created_at, last_seen_at) VALUES (?1, ?2, ?3, ?3) "
        "ON CONFLICT(primary_email) DO UPDATE SET last_seen_at = ?3"
    ).bind(new_id("usr"), email, now).run()
    user = await db.prepare("SELECT id FROM users WHERE primary_email = ?1").bind(email).first()
    if not user:
        return None

    await db.prepare(
        "INSERT OR IGNORE INTO auth_accounts (provider, provider_user_id, user_id, created_at) "
        "VALUES ('stytch', ?1, ?2, ?3)"
    ).bind(s.member_id, user["id"], now).run()
    await db.prepare(
        "INSERT OR IGNORE INTO tenant_memberships (tenant_id, user_id, role, created_at) VALUES (?1, ?2, ?3, ?4)"
    ).bind(tenant["id"], user["id"], "owner" if new_tenant else "member", now).run()

    return {"tenant_id": tenant["id"], "user_id": user["id"]}
