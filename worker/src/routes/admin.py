"""Operator-facing admin API (port of routes/admin.ts). Mounted at /v1/admin.

Authenticated by :func:`auth.require_operator` (Stytch session or admin token) and
scoped to the operator's tenant on every query.
"""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from auth import OperatorAuth, generate_agent_token, hash_token, require_operator
from bodies import MISSING, field, json_body
from deps import get_env
from env import Env
from errors import http_error
from ids import new_id, now_seconds
from notify import fire_alert
from schema import (
    ALERT_KINDS,
    COMMAND_KINDS,
    ROUTE_KINDS,
    SEVERITIES,
    TRANSPORTS,
    as_enum,
    as_int,
    as_optional_bool,
    as_optional_enum,
    as_optional_int,
    as_optional_string,
    as_string,
    as_string_array,
)

router = APIRouter(prefix="/v1/admin")

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_GIT_URL_RE = re.compile(r"^(https://|ssh://|git@)")


# --- Agents ---------------------------------------------------------------


@router.post("/agents")
async def create_agent(request: Request, auth: OperatorAuth = Depends(require_operator), env: Env = Depends(get_env)):
    body = await json_body(request)
    name = as_string(field(body, "name"), "name", max=100)
    if not name.ok:
        raise http_error(400, name.error)

    token = generate_agent_token()
    token_hash = hash_token(token)
    agent_id = new_id("agent")
    now = now_seconds()
    try:
        await env.db.prepare(
            "INSERT INTO agents (id, name, token_hash, created_at, tenant_id) VALUES (?1, ?2, ?3, ?4, ?5)"
        ).bind(agent_id, name.value, token_hash, now, auth.tenant_id).run()
    except Exception as err:  # noqa: BLE001
        if "UNIQUE" in str(err):
            raise http_error(409, "agent name already exists")
        raise
    return JSONResponse({"id": agent_id, "name": name.value, "token": token, "created_at": now}, status_code=201)


@router.get("/agents")
async def list_agents(auth: OperatorAuth = Depends(require_operator), env: Env = Depends(get_env)):
    rows = await env.db.prepare(
        "SELECT id, name, created_at, last_seen_at, disabled, public_key, "
        "git_remote_url, git_remote_branch, "
        "CASE WHEN git_remote_token_sealed IS NOT NULL THEN 1 ELSE 0 END AS git_remote_has_token "
        "FROM agents WHERE tenant_id = ?1 ORDER BY created_at DESC"
    ).bind(auth.tenant_id).all()
    return {"agents": rows}


@router.post("/agents/{id}/disable")
async def disable_agent(id: str, auth: OperatorAuth = Depends(require_operator), env: Env = Depends(get_env)):
    res = await env.db.prepare("UPDATE agents SET disabled = 1 WHERE id = ?1 AND tenant_id = ?2").bind(
        id, auth.tenant_id
    ).run()
    if res.changes == 0:
        raise http_error(404, "not found")
    return {"ok": True}


@router.post("/agents/{id}/rotate-token")
async def rotate_token(id: str, auth: OperatorAuth = Depends(require_operator), env: Env = Depends(get_env)):
    token = generate_agent_token()
    token_hash = hash_token(token)
    res = await env.db.prepare(
        "UPDATE agents SET token_hash = ?1, disabled = 0 WHERE id = ?2 AND tenant_id = ?3"
    ).bind(token_hash, id, auth.tenant_id).run()
    if res.changes == 0:
        raise http_error(404, "not found")
    return {"id": id, "token": token}


@router.post("/agents/{id}/git-remote")
async def set_git_remote(id: str, request: Request, auth: OperatorAuth = Depends(require_operator), env: Env = Depends(get_env)):
    tenant_id = auth.tenant_id
    body = await json_body(request)
    if not isinstance(body, dict):
        raise http_error(400, "invalid JSON body")

    # Clearing the remote must be EXPLICIT: `url` present and null/"".
    if "url" in body and (body["url"] is None or body["url"] == ""):
        res = await env.db.prepare(
            "UPDATE agents SET git_remote_url = NULL, git_remote_branch = NULL, "
            "git_remote_token_sealed = NULL WHERE id = ?1 AND tenant_id = ?2"
        ).bind(id, tenant_id).run()
        if res.changes == 0:
            raise http_error(404, "agent not found")
        return {"ok": True, "cleared": True}

    url = as_string(field(body, "url"), "url", max=500)
    if not url.ok:
        raise http_error(400, url.error)
    if not _GIT_URL_RE.match(url.value):
        raise http_error(400, "url must be an https://, ssh://, or git@ remote")
    branch = as_optional_string(field(body, "branch"), "branch", max=100)
    if not branch.ok:
        raise http_error(400, branch.error)

    sealed = body.get("token_sealed", MISSING)
    if sealed is not None and sealed is not MISSING and not isinstance(sealed, str):
        raise http_error(400, "token_sealed must be a string or null")
    if isinstance(sealed, str) and len(sealed) > 10000:
        raise http_error(400, "token_sealed exceeds 10000 chars")

    branch_val = branch.value or "main"
    if sealed is MISSING:
        res = await env.db.prepare(
            "UPDATE agents SET git_remote_url = ?1, git_remote_branch = ?2 WHERE id = ?3 AND tenant_id = ?4"
        ).bind(url.value, branch_val, id, tenant_id).run()
    else:
        res = await env.db.prepare(
            "UPDATE agents SET git_remote_url = ?1, git_remote_branch = ?2, "
            "git_remote_token_sealed = ?3 WHERE id = ?4 AND tenant_id = ?5"
        ).bind(url.value, branch_val, sealed or None, id, tenant_id).run()
    if res.changes == 0:
        raise http_error(404, "agent not found")
    return {"ok": True}


@router.delete("/agents/{id}")
async def delete_agent(id: str, auth: OperatorAuth = Depends(require_operator), env: Env = Depends(get_env)):
    tenant_id = auth.tenant_id
    results = await env.db.batch(
        [
            env.db.prepare(
                "DELETE FROM devices WHERE agent_id = ?1 AND agent_id IN (SELECT id FROM agents WHERE tenant_id = ?2)"
            ).bind(id, tenant_id),
            env.db.prepare("DELETE FROM agents WHERE id = ?1 AND tenant_id = ?2").bind(id, tenant_id),
        ]
    )
    if results[1].changes == 0:
        raise http_error(404, "not found")
    return {"ok": True}


# --- Devices --------------------------------------------------------------


@router.post("/devices")
async def upsert_device(request: Request, auth: OperatorAuth = Depends(require_operator), env: Env = Depends(get_env)):
    body = await json_body(request)
    agent_id = as_string(field(body, "agent_id"), "agent_id")
    if not agent_id.ok:
        raise http_error(400, agent_id.error)
    name = as_string(field(body, "name"), "name", max=100)
    if not name.ok:
        raise http_error(400, name.error)
    site = as_optional_string(field(body, "site"), "site", max=100)
    if not site.ok:
        raise http_error(400, site.error)
    role = as_optional_string(field(body, "role"), "role", max=100)
    if not role.ok:
        raise http_error(400, role.error)
    tags = as_string_array(field(body, "tags"), "tags")
    if not tags.ok:
        raise http_error(400, tags.error)
    interval = as_optional_int(field(body, "heartbeat_interval_seconds"), "heartbeat_interval_seconds", min=30, max=86400)
    if not interval.ok:
        raise http_error(400, interval.error)
    grace = as_optional_int(field(body, "grace_seconds"), "grace_seconds", min=0, max=86400)
    if not grace.ok:
        raise http_error(400, grace.error)
    label = as_optional_string(field(body, "label"), "label", max=100)
    if not label.ok:
        raise http_error(400, label.error)

    address = as_optional_string(field(body, "address"), "address", max=255)
    if not address.ok:
        raise http_error(400, address.error)
    username = as_optional_string(field(body, "username"), "username", max=100)
    if not username.ok:
        raise http_error(400, username.error)
    password_env = as_optional_string(field(body, "password_env"), "password_env", max=100)
    if not password_env.ok:
        raise http_error(400, password_env.error)
    ssh_key_path = as_optional_string(field(body, "ssh_key_path"), "ssh_key_path", max=255)
    if not ssh_key_path.ok:
        raise http_error(400, ssh_key_path.error)
    t_primary = as_optional_enum(field(body, "transport_primary"), "transport_primary", TRANSPORTS)
    if not t_primary.ok:
        raise http_error(400, t_primary.error)
    t_fallback = as_optional_enum(field(body, "transport_fallback"), "transport_fallback", TRANSPORTS)
    if not t_fallback.ok:
        raise http_error(400, t_fallback.error)
    api_port = as_optional_int(field(body, "api_port"), "api_port", min=1, max=65535)
    if not api_port.ok:
        raise http_error(400, api_port.error)
    ssh_port = as_optional_int(field(body, "ssh_port"), "ssh_port", min=1, max=65535)
    if not ssh_port.ok:
        raise http_error(400, ssh_port.error)
    use_tls = as_optional_bool(field(body, "use_tls"), "use_tls")
    if not use_tls.ok:
        raise http_error(400, use_tls.error)
    use_tls_int = None if use_tls.value is None else (1 if use_tls.value else 0)

    agent = await env.db.prepare(
        "SELECT id FROM agents WHERE id = ?1 AND disabled = 0 AND tenant_id = ?2"
    ).bind(agent_id.value, auth.tenant_id).first()
    if not agent:
        raise http_error(404, "agent not found")

    existing = await env.db.prepare("SELECT id FROM devices WHERE agent_id = ?1 AND name = ?2").bind(
        agent_id.value, name.value
    ).first()

    dev_id = existing["id"] if existing else new_id("dev")
    now = now_seconds()
    tags_json = json.dumps(tags.value) if tags.value else None

    if existing:
        await env.db.prepare(
            "UPDATE devices SET "
            "site = COALESCE(?1, site), role = COALESCE(?2, role), tags = COALESCE(?3, tags), "
            "heartbeat_interval_seconds = COALESCE(?4, heartbeat_interval_seconds), "
            "grace_seconds = COALESCE(?5, grace_seconds), "
            "address = COALESCE(?6, address), username = COALESCE(?7, username), "
            "password_env = COALESCE(?8, password_env), ssh_key_path = COALESCE(?9, ssh_key_path), "
            "transport_primary = COALESCE(?10, transport_primary), "
            "transport_fallback = COALESCE(?11, transport_fallback), "
            "api_port = COALESCE(?12, api_port), use_tls = COALESCE(?13, use_tls), "
            "ssh_port = COALESCE(?14, ssh_port), label = COALESCE(?15, label) WHERE id = ?16"
        ).bind(
            site.value,
            role.value,
            tags_json,
            interval.value,
            grace.value,
            address.value,
            username.value,
            password_env.value,
            ssh_key_path.value,
            t_primary.value,
            t_fallback.value,
            api_port.value,
            use_tls_int,
            ssh_port.value,
            label.value,
            dev_id,
        ).run()
    else:
        await env.db.prepare(
            "INSERT INTO devices "
            "(id, agent_id, name, site, role, tags, heartbeat_interval_seconds, grace_seconds, "
            "address, username, password_env, ssh_key_path, transport_primary, transport_fallback, "
            "api_port, use_tls, ssh_port, label, last_status, created_at) "
            "VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16, ?17, ?18, 'unknown', ?19)"
        ).bind(
            dev_id,
            agent_id.value,
            name.value,
            site.value,
            role.value,
            tags_json,
            interval.value,
            grace.value,
            address.value,
            username.value,
            password_env.value,
            ssh_key_path.value,
            t_primary.value,
            t_fallback.value,
            api_port.value,
            use_tls_int,
            ssh_port.value,
            label.value,
            now,
        ).run()
    return {"id": dev_id, "upserted": existing is None}


@router.get("/devices")
async def list_devices(auth: OperatorAuth = Depends(require_operator), env: Env = Depends(get_env)):
    rows = await env.db.prepare(
        "SELECT id, agent_id, name, site, role, tags, heartbeat_interval_seconds, grace_seconds, "
        "last_seen_at, last_status, last_status_changed_at, created_at "
        "FROM devices WHERE agent_id IN (SELECT id FROM agents WHERE tenant_id = ?1) ORDER BY name"
    ).bind(auth.tenant_id).all()
    return {"devices": rows}


@router.delete("/devices/{id}")
async def delete_device(id: str, auth: OperatorAuth = Depends(require_operator), env: Env = Depends(get_env)):
    res = await env.db.prepare(
        "DELETE FROM devices WHERE id = ?1 AND agent_id IN (SELECT id FROM agents WHERE tenant_id = ?2)"
    ).bind(id, auth.tenant_id).run()
    if res.changes == 0:
        raise http_error(404, "not found")
    return {"ok": True}


@router.post("/devices/{id}/reassign")
async def reassign_device(id: str, request: Request, auth: OperatorAuth = Depends(require_operator), env: Env = Depends(get_env)):
    body = await json_body(request)
    agent_id = as_string(field(body, "agent_id"), "agent_id")
    if not agent_id.ok:
        raise http_error(400, agent_id.error)
    tenant_id = auth.tenant_id
    agent = await env.db.prepare(
        "SELECT id FROM agents WHERE id = ?1 AND tenant_id = ?2 AND disabled = 0"
    ).bind(agent_id.value, tenant_id).first()
    if not agent:
        raise http_error(404, "agent not found")
    try:
        res = await env.db.prepare(
            "UPDATE devices SET agent_id = ?1 WHERE id = ?2 AND agent_id IN (SELECT id FROM agents WHERE tenant_id = ?3)"
        ).bind(agent_id.value, id, tenant_id).run()
        if res.changes == 0:
            raise http_error(404, "device not found")
    except Exception as err:  # noqa: BLE001
        if "UNIQUE" in str(err):
            raise http_error(409, "that agent already has a device with this name")
        raise
    return {"ok": True}


@router.post("/devices/{id}/sealed-credential")
async def set_sealed_credential(id: str, request: Request, auth: OperatorAuth = Depends(require_operator), env: Env = Depends(get_env)):
    body = await json_body(request)
    sealed = field(body, "sealed")
    if sealed is not None and not isinstance(sealed, str):
        raise http_error(400, "sealed must be a string (to set) or null (to clear)")
    if isinstance(sealed, str) and len(sealed) > 10000:
        raise http_error(400, "sealed blob exceeds 10000 chars")
    res = await env.db.prepare(
        "UPDATE devices SET credential_sealed = ?1 "
        "WHERE id = ?2 AND agent_id IN (SELECT id FROM agents WHERE tenant_id = ?3)"
    ).bind(sealed, id, auth.tenant_id).run()
    if res.changes == 0:
        raise http_error(404, "not found")
    return {"ok": True}


# --- Alert routes ---------------------------------------------------------


@router.post("/alert-routes")
async def create_alert_route(request: Request, auth: OperatorAuth = Depends(require_operator), env: Env = Depends(get_env)):
    body = await json_body(request)
    name = as_string(field(body, "name"), "name", max=100)
    if not name.ok:
        raise http_error(400, name.error)
    kind = as_enum(field(body, "kind"), "kind", ROUTE_KINDS)
    if not kind.ok:
        raise http_error(400, kind.error)
    url = as_string(field(body, "url"), "url", max=1000, pattern=r"^https?://")
    if not url.ok:
        raise http_error(400, url.error)
    events = as_string_array(field(body, "events"), "events")
    if not events.ok:
        raise http_error(400, events.error)
    if events.value:
        for ev in events.value:
            if ev not in ALERT_KINDS:
                raise http_error(400, f"unknown event '{ev}'")
    min_severity = field(body, "min_severity") or "warning"
    if min_severity not in SEVERITIES:
        raise http_error(400, "invalid min_severity")

    route_id = new_id("route")
    try:
        await env.db.prepare(
            "INSERT INTO alert_routes (id, name, kind, url, events, min_severity, enabled, created_at, tenant_id) "
            "VALUES (?1, ?2, ?3, ?4, ?5, ?6, 1, ?7, ?8)"
        ).bind(
            route_id,
            name.value,
            kind.value,
            url.value,
            json.dumps(events.value) if events.value else None,
            min_severity,
            now_seconds(),
            auth.tenant_id,
        ).run()
    except Exception as err:  # noqa: BLE001
        if "UNIQUE" in str(err):
            raise http_error(409, "route name already exists")
        raise
    return JSONResponse({"id": route_id, "name": name.value}, status_code=201)


@router.get("/alert-routes")
async def list_alert_routes(auth: OperatorAuth = Depends(require_operator), env: Env = Depends(get_env)):
    rows = await env.db.prepare(
        "SELECT id, name, kind, url, events, min_severity, enabled, created_at "
        "FROM alert_routes WHERE tenant_id = ?1 ORDER BY name"
    ).bind(auth.tenant_id).all()
    return {"routes": rows}


@router.delete("/alert-routes/{id}")
async def delete_alert_route(id: str, auth: OperatorAuth = Depends(require_operator), env: Env = Depends(get_env)):
    res = await env.db.prepare("DELETE FROM alert_routes WHERE id = ?1 AND tenant_id = ?2").bind(
        id, auth.tenant_id
    ).run()
    if res.changes == 0:
        raise http_error(404, "not found")
    return {"ok": True}


# --- Test alert -----------------------------------------------------------


@router.post("/alerts/test")
async def test_alert(request: Request, auth: OperatorAuth = Depends(require_operator), env: Env = Depends(get_env)):
    body = await json_body(request)
    message = field(body, "message") if isinstance(field(body, "message"), str) else "Test alert from Mikrotik Minder"
    alert_id = await fire_alert(
        env,
        {
            "severity": "info",
            "kind": "manual",
            "title": message,
            "payload": {"source": "admin", "note": "manual test"},
            "tenant_id": auth.tenant_id,
        },
    )
    return {"ok": True, "alert_id": alert_id}


# --- Commands -------------------------------------------------------------


@router.post("/commands")
async def enqueue_command(request: Request, auth: OperatorAuth = Depends(require_operator), env: Env = Depends(get_env)):
    body = await json_body(request)
    device_id = as_string(field(body, "device_id"), "device_id", max=100)
    if not device_id.ok:
        raise http_error(400, device_id.error)
    kind = as_enum(field(body, "kind"), "kind", COMMAND_KINDS)
    if not kind.ok:
        raise http_error(400, kind.error)
    scheduled_for = as_optional_int(field(body, "scheduled_for"), "scheduled_for", min=0)
    if not scheduled_for.ok:
        raise http_error(400, scheduled_for.error)
    raw_email = (request.headers.get("X-Auth-Email") or "").strip()
    requested_by = raw_email if 0 < len(raw_email) <= 254 and _EMAIL_RE.match(raw_email) else "unknown"
    params = field(body, "params", default=MISSING)
    if params is not MISSING and not isinstance(params, dict):
        raise http_error(400, "params must be an object")

    dev = await env.db.prepare(
        "SELECT id, agent_id FROM devices "
        "WHERE id = ?1 AND agent_id IN (SELECT id FROM agents WHERE tenant_id = ?2)"
    ).bind(device_id.value, auth.tenant_id).first()
    if not dev:
        raise http_error(404, "device not found")

    cmd_id = new_id("cmd")
    await env.db.prepare(
        "INSERT INTO commands (id, device_id, agent_id, kind, params, status, scheduled_for, requested_by, created_at) "
        "VALUES (?1, ?2, ?3, ?4, ?5, 'pending', ?6, ?7, ?8)"
    ).bind(
        cmd_id,
        dev["id"],
        dev["agent_id"],
        kind.value,
        json.dumps(params) if params is not MISSING else None,
        scheduled_for.value,
        requested_by,
        now_seconds(),
    ).run()
    return JSONResponse({"id": cmd_id, "status": "pending"}, status_code=201)


@router.get("/commands/{id}/artifact")
async def get_artifact(id: str, auth: OperatorAuth = Depends(require_operator), env: Env = Depends(get_env)):
    tenant_id = auth.tenant_id
    row = await env.db.prepare(
        "SELECT artifact FROM commands "
        "WHERE id = ?1 AND artifact IS NOT NULL AND agent_id IN (SELECT id FROM agents WHERE tenant_id = ?2)"
    ).bind(id, tenant_id).first()
    if not row or row["artifact"] is None:
        cmd = await env.db.prepare(
            "SELECT id, status FROM commands WHERE id = ?1 AND agent_id IN (SELECT id FROM agents WHERE tenant_id = ?2)"
        ).bind(id, tenant_id).first()
        if not cmd:
            raise http_error(404, "not found")
        if cmd["status"] in ("pending", "claimed"):
            raise http_error(202, "command not yet ready")
        raise http_error(410, "no artifact — already downloaded, or none produced")
    await env.db.prepare(
        "UPDATE commands SET artifact = NULL "
        "WHERE id = ?1 AND artifact IS NOT NULL AND agent_id IN (SELECT id FROM agents WHERE tenant_id = ?2)"
    ).bind(id, tenant_id).run()
    return Response(
        content=row["artifact"],
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


# --- Backups --------------------------------------------------------------


@router.get("/devices/{id}/backups")
async def list_device_backups(id: str, auth: OperatorAuth = Depends(require_operator), env: Env = Depends(get_env)):
    rows = await env.db.prepare(
        "SELECT id, file_name, size_bytes, sha256, created_at FROM backup_files "
        "WHERE device_id = ?1 AND agent_id IN (SELECT id FROM agents WHERE tenant_id = ?2) "
        "ORDER BY created_at DESC LIMIT 200"
    ).bind(id, auth.tenant_id).all()
    return {"backups": rows}


@router.get("/backups/{id}/download")
async def download_backup(id: str, auth: OperatorAuth = Depends(require_operator), env: Env = Depends(get_env)):
    row = await env.db.prepare(
        "SELECT file_name, r2_key, sha256 FROM backup_files "
        "WHERE id = ?1 AND agent_id IN (SELECT id FROM agents WHERE tenant_id = ?2)"
    ).bind(id, auth.tenant_id).first()
    if not row:
        raise http_error(404, "not found")

    obj = await env.backups.get(row["r2_key"])
    if not obj:
        raise http_error(410, "backup body missing from storage")
    headers = {
        "content-disposition": f'attachment; filename="{row["file_name"]}"',
        "x-content-sha256": row["sha256"],
        "Cache-Control": "no-store",
    }
    if obj.size is not None:
        headers["content-length"] = str(obj.size)
    return Response(content=await obj.bytes(), media_type="application/octet-stream", headers=headers)
