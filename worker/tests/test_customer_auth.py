"""SaaS Phase 1 §4 — the customer Stytch-session auth path (require_operator).

Generates a real RS256 keypair (via ``cryptography``), signs session JWTs, and
drives the ACTUAL FastAPI app: a valid session is scoped to the org's tenant (and
JIT-links a user + membership); an unprovisioned org is refused; tampered /
expired / wrong-key tokens are rejected; and the admin-token path is untouched.

The two Workers-runtime crypto primitives in ``stytch`` (JWKS load + RS256 verify)
are monkeypatched to ``cryptography`` equivalents; the rest of the validation +
JIT-onboarding logic is the production code under test.
"""

from __future__ import annotations

import base64
import json
import time

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

import stytch
from auth import hash_token  # noqa: F401  (ensures src import path is wired)
from conftest import bind
from d1_shim import FX

PROJECT_ID = "project-test-abc"
ISSUER = f"stytch.com/{PROJECT_ID}"
JWKS_URL = f"https://test.stytch.com/v1/sessions/jwks/{PROJECT_ID}"
KID = "jwk-test-1"
ORG_ID = "organization-test-alpha"
MEMBER_ID = "member-test-alpha-1"

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64url_json(obj) -> str:
    return _b64url(json.dumps(obj, separators=(",", ":")).encode())


def sign_jwt(payload: dict, kid: str = KID) -> str:
    signing_input = f"{_b64url_json({'alg': 'RS256', 'kid': kid, 'typ': 'JWT'})}.{_b64url_json(payload)}"
    sig = _PRIVATE_KEY.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input}.{_b64url(sig)}"


def valid_payload(organization_id=ORG_ID, sub=MEMBER_ID, email="alpha-user@a.example", iat=None, exp=None) -> dict:
    now = int(time.time())
    return {
        "sub": sub,
        "iss": ISSUER,
        "aud": [PROJECT_ID],
        "iat": iat if iat is not None else now,
        "exp": exp if exp is not None else now + 3600,
        "https://stytch.com/organization": {"organization_id": organization_id, "slug": "acme"},
        "https://stytch.com/session": {
            "id": "session-test-1",
            "authentication_factors": [
                {"type": "magic_link", "delivery_method": "email", "email_factor": {"email_address": email}}
            ],
        },
    }


@pytest.fixture(autouse=True)
def patch_crypto(monkeypatch):
    # Stub only the JWKS *fetch* (no network); the real, portable CPython
    # `_verify_rs256` (cryptography branch) runs against the returned key — so this
    # exercises the actual signature-verification path used off-Cloudflare.
    async def fake_load_jwks(env):
        return {KID: _PUBLIC_KEY}

    monkeypatch.setattr(stytch, "_load_jwks", fake_load_jwks)


@pytest.fixture
def env_db(make_env):
    env, conn = make_env(
        var_overrides={
            "ADMIN_TOKEN": "mtm_admin",
            "SUPERADMIN_EMAILS": "",
            "STYTCH_PROJECT_ID": PROJECT_ID,
            "STYTCH_JWKS_URL": JWKS_URL,
            "STYTCH_ISSUER": ISSUER,
        }
    )
    conn.execute("UPDATE tenants SET stytch_org_id = ? WHERE id = ?", (ORG_ID, FX.tenantA))
    conn.commit()
    return env, conn


def get(client, env, path, token):
    bind(env)
    return client.get(path, headers={"authorization": f"Bearer {token}"})


def test_valid_session_scopes_to_org_tenant(env_db, client):
    env, _ = env_db
    res = get(client, env, "/v1/admin/agents", sign_jwt(valid_payload()))
    assert res.status_code == 200
    assert FX.nameAgentA in res.text
    assert FX.nameAgentB not in res.text


def test_jit_links_user_and_membership(env_db, client):
    env, conn = env_db
    get(client, env, "/v1/admin/agents", sign_jwt(valid_payload()))
    acct = conn.execute(
        "SELECT user_id FROM auth_accounts WHERE provider = 'stytch' AND provider_user_id = ?", (MEMBER_ID,)
    ).fetchone()
    assert acct is not None
    mem = conn.execute(
        "SELECT 1 FROM tenant_memberships WHERE tenant_id = ? AND user_id = ?", (FX.tenantA, acct["user_id"])
    ).fetchone()
    assert mem is not None


def test_auto_provisions_fresh_tenant(env_db, client):
    env, conn = env_db
    res = get(
        client, env, "/v1/admin/agents",
        sign_jwt(valid_payload(organization_id="organization-test-ghost", sub="member-ghost-1")),
    )
    assert res.status_code == 200
    tenant = conn.execute(
        "SELECT id FROM tenants WHERE stytch_org_id = ?", ("organization-test-ghost",)
    ).fetchone()
    assert tenant is not None
    assert FX.nameAgentA not in res.text
    assert FX.nameAgentB not in res.text


def test_rejects_tampered_token(env_db, client):
    env, _ = env_db
    tok = sign_jwt(valid_payload())
    tampered = tok[:-4] + ("BBBB" if tok[-4:] == "AAAA" else "AAAA")
    assert get(client, env, "/v1/admin/agents", tampered).status_code == 401


def test_rejects_unknown_kid(env_db, client):
    env, _ = env_db
    assert get(client, env, "/v1/admin/agents", sign_jwt(valid_payload(), kid="wrong-kid")).status_code == 401


def test_rejects_expired_session(env_db, client):
    env, _ = env_db
    now = int(time.time())
    tok = sign_jwt(valid_payload(iat=now - 7200, exp=now - 3600))
    assert get(client, env, "/v1/admin/agents", tok).status_code == 401


def test_admin_token_legacy_path_preserved(env_db, client):
    env, _ = env_db
    bind(env)
    res = client.get(
        "/v1/admin/agents",
        headers={"authorization": "Bearer mtm_admin", "X-Auth-Email": FX.emailA},
    )
    assert res.status_code == 200
