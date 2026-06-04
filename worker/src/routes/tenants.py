"""Tenant lifecycle (port of routes/tenants.ts). Mounted at /v1/superadmin/tenants.

Superadmin-only (admin token + an ``X-Auth-Email`` in ``SUPERADMIN_EMAILS``); these
ops are cross-tenant so they bypass the tenant-scoping operator middleware.
"""

from __future__ import annotations

from urllib.parse import unquote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from auth import require_superadmin
from bodies import field, json_body
from deps import get_env
from env import Env
from errors import http_error
from ids import new_id, now_seconds
from schema import as_string

router = APIRouter(prefix="/v1/superadmin/tenants", dependencies=[Depends(require_superadmin)])

_EMAIL_RE = r"^[^\s@]+@[^\s@]+\.[^\s@]+$"


@router.post("")
async def create_tenant(request: Request, env: Env = Depends(get_env)):
    body = await json_body(request)
    name = as_string(field(body, "name"), "name", max=100)
    if not name.ok:
        raise http_error(400, name.error)
    tenant_id = new_id("tnt")
    now = now_seconds()
    await env.db.prepare("INSERT INTO tenants (id, name, created_at) VALUES (?1, ?2, ?3)").bind(
        tenant_id, name.value, now
    ).run()
    return JSONResponse({"id": tenant_id, "name": name.value, "created_at": now}, status_code=201)


@router.get("")
async def list_tenants(env: Env = Depends(get_env)):
    rows = await env.db.prepare("SELECT id, name, created_at FROM tenants ORDER BY created_at DESC").all()
    return {"tenants": rows}


@router.post("/{id}/members")
async def add_member(id: str, request: Request, env: Env = Depends(get_env)):
    body = await json_body(request)
    email = as_string(field(body, "email"), "email", max=254, pattern=_EMAIL_RE)
    if not email.ok:
        raise http_error(400, email.error)
    tenant = await env.db.prepare("SELECT id FROM tenants WHERE id = ?1").bind(id).first()
    if not tenant:
        raise http_error(404, "tenant not found")
    await env.db.prepare(
        "INSERT INTO tenant_members (email, tenant_id, created_at) VALUES (?1, ?2, ?3) "
        "ON CONFLICT(email) DO UPDATE SET tenant_id = excluded.tenant_id"
    ).bind(email.value.lower(), id, now_seconds()).run()
    return JSONResponse({"email": email.value.lower(), "tenant_id": id}, status_code=201)


@router.get("/{id}/members")
async def list_members(id: str, env: Env = Depends(get_env)):
    rows = await env.db.prepare(
        "SELECT email, created_at FROM tenant_members WHERE tenant_id = ?1 ORDER BY email"
    ).bind(id).all()
    return {"members": rows}


@router.delete("/{id}/members/{email}")
async def remove_member(id: str, email: str, env: Env = Depends(get_env)):
    res = await env.db.prepare("DELETE FROM tenant_members WHERE tenant_id = ?1 AND email = ?2").bind(
        id, unquote(email).lower()
    ).run()
    if res.changes == 0:
        raise http_error(404, "not found")
    return {"ok": True}
