"""Agent-facing ingest API (port of routes/ingest.ts). Mounted at /v1/ingest.

Every route authenticates the agent by its ``mtm_…`` bearer token.
"""

from __future__ import annotations

import hashlib
import json
import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from auth import require_agent
from bodies import MISSING as _MISSING
from bodies import field, json_body
from deps import get_env
from env import Env
from errors import http_error
from ids import new_id, now_seconds
from notify import fire_alert
from schema import (
    DEVICE_STATUSES,
    JOB_KINDS,
    JOB_STATUSES,
    as_enum,
    as_int,
    as_optional_string,
    as_string,
)

router = APIRouter(prefix="/v1/ingest")

MAX_BACKUP_BYTES = 64 * 1024 * 1024
BACKUP_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.backup$")
_SHA_RE = re.compile(r"^[a-f0-9]{64}$")


async def _find_or_create_device(env: Env, agent_id: str, identifier: str) -> dict:
    row = await env.db.prepare(
        "SELECT id, name, last_status FROM devices WHERE agent_id = ?1 AND (name = ?2 OR id = ?2)"
    ).bind(agent_id, identifier).first()
    if row:
        return {"id": row["id"], "name": row["name"], "created": False, "previous_status": row["last_status"]}

    dev_id = new_id("dev")
    await env.db.prepare(
        "INSERT INTO devices (id, agent_id, name, last_status, created_at) VALUES (?1, ?2, ?3, 'unknown', ?4)"
    ).bind(dev_id, agent_id, identifier, now_seconds()).run()
    return {"id": dev_id, "name": identifier, "created": True, "previous_status": "unknown"}


@router.post("/heartbeat")
async def heartbeat(request: Request, agent_id: str = Depends(require_agent), env: Env = Depends(get_env)):
    body = await json_body(request)
    device = as_string(field(body, "device"), "device", max=100)
    if not device.ok:
        raise http_error(400, device.error)
    status = "ok"
    if field(body, "status") is not None:
        s = as_enum(field(body, "status"), "status", DEVICE_STATUSES)
        if not s.ok:
            raise http_error(400, s.error)
        status = s.value

    dev = await _find_or_create_device(env, agent_id, device.value)
    now = now_seconds()
    status_changed = dev["previous_status"] != status
    await env.db.prepare(
        "UPDATE devices SET last_seen_at = ?1, last_status = ?2, "
        "last_status_changed_at = CASE WHEN ?3 = 1 THEN ?1 ELSE last_status_changed_at END WHERE id = ?4"
    ).bind(now, status, 1 if status_changed else 0, dev["id"]).run()
    agent_ip = request.headers.get("cf-connecting-ip")
    await env.db.prepare("UPDATE agents SET last_seen_at = ?1, last_ip = ?2 WHERE id = ?3").bind(
        now, agent_ip, agent_id
    ).run()

    if dev["previous_status"] == "down" and status != "down":
        await fire_alert(
            env,
            {
                "severity": "info",
                "kind": "heartbeat_recovered",
                "agent_id": agent_id,
                "device_id": dev["id"],
                "title": f"{dev['name']} is back online",
                "payload": {"device": dev["name"], "previous_status": dev["previous_status"], "status": status},
            },
        )

    return {"ok": True, "device_id": dev["id"], "created": dev["created"]}


@router.post("/jobs")
async def jobs(request: Request, agent_id: str = Depends(require_agent), env: Env = Depends(get_env)):
    body = await json_body(request)
    kind = as_enum(field(body, "kind"), "kind", JOB_KINDS)
    if not kind.ok:
        raise http_error(400, kind.error)
    status = as_enum(field(body, "status"), "status", JOB_STATUSES)
    if not status.ok:
        raise http_error(400, status.error)
    started = as_int(field(body, "started_at"), "started_at", min=0)
    if not started.ok:
        raise http_error(400, started.error)
    finished = as_int(field(body, "finished_at"), "finished_at", min=0)
    if not finished.ok:
        raise http_error(400, finished.error)
    if finished.value < started.value:
        raise http_error(400, "finished_at must be >= started_at")
    summary = as_optional_string(field(body, "summary"), "summary", max=500)
    if not summary.ok:
        raise http_error(400, summary.error)
    device_name = as_optional_string(field(body, "device"), "device", max=100)
    if not device_name.ok:
        raise http_error(400, device_name.error)

    device_id = None
    device_label = None
    if device_name.value:
        dev = await _find_or_create_device(env, agent_id, device_name.value)
        device_id = dev["id"]
        device_label = dev["name"]

    job_id = new_id("job")
    raw_details = field(body, "details", default=_MISSING)
    details_json = json.dumps(raw_details) if raw_details is not _MISSING else None
    await env.db.prepare(
        "INSERT INTO jobs (id, agent_id, device_id, kind, status, started_at, finished_at, summary, details, created_at) "
        "VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)"
    ).bind(
        job_id,
        agent_id,
        device_id,
        kind.value,
        status.value,
        started.value,
        finished.value,
        summary.value,
        details_json,
        now_seconds(),
    ).run()
    await env.db.prepare("UPDATE agents SET last_seen_at = ?1 WHERE id = ?2").bind(now_seconds(), agent_id).run()

    k, st, sm = kind.value, status.value, summary.value
    if st == "failed":
        critical = k in ("update_apply", "firmware_align")
        await fire_alert(
            env,
            {
                "severity": "critical" if critical else "warning",
                "kind": "update_failed" if critical else "job_failed",
                "agent_id": agent_id,
                "device_id": device_id,
                "job_id": job_id,
                "title": f"{k} failed" + (f" on {device_label}" if device_label else ""),
                "payload": {"kind": k, "summary": sm, "device": device_label},
            },
        )
    elif k == "drift" and st == "warning":
        await fire_alert(
            env,
            {
                "severity": "info",
                "kind": "drift_detected",
                "agent_id": agent_id,
                "device_id": device_id,
                "job_id": job_id,
                "title": "Config drift detected" + (f" on {device_label}" if device_label else ""),
                "payload": {"summary": sm, "device": device_label},
            },
        )
    elif k in ("update_check", "firmware_align") and st == "warning":
        await fire_alert(
            env,
            {
                "severity": "warning",
                "kind": "update_available",
                "agent_id": agent_id,
                "device_id": device_id,
                "job_id": job_id,
                "title": ("Firmware mismatch" if k == "firmware_align" else "Update available")
                + (f" on {device_label}" if device_label else ""),
                "payload": {"kind": k, "summary": sm, "device": device_label},
            },
        )
    elif st == "success" and k == "backup":
        await fire_alert(
            env,
            {
                "severity": "info",
                "kind": "backup_succeeded",
                "agent_id": agent_id,
                "device_id": device_id,
                "job_id": job_id,
                "title": "Backup completed" + (f" for {device_label}" if device_label else ""),
                "payload": {"device": device_label, "summary": sm},
            },
        )
    elif st == "success" and k == "update_apply":
        await fire_alert(
            env,
            {
                "severity": "info",
                "kind": "update_applied",
                "agent_id": agent_id,
                "device_id": device_id,
                "job_id": job_id,
                "title": "Update applied" + (f" to {device_label}" if device_label else ""),
                "payload": {"device": device_label, "summary": sm},
            },
        )

    return JSONResponse({"ok": True, "job_id": job_id}, status_code=201)


@router.get("/commands")
async def commands(agent_id: str = Depends(require_agent), env: Env = Depends(get_env)):
    now = now_seconds()
    rows = await env.db.prepare(
        "UPDATE commands SET status = 'claimed', claimed_at = ?1 "
        "WHERE id IN ("
        "  SELECT id FROM commands"
        "  WHERE agent_id = ?2 AND status = 'pending'"
        "    AND (scheduled_for IS NULL OR scheduled_for <= ?1)"
        "  ORDER BY created_at LIMIT 20"
        ") "
        "RETURNING commands.id, commands.device_id, commands.kind, commands.params, "
        "(SELECT name FROM devices WHERE id = commands.device_id) AS device_name"
    ).bind(now, agent_id).all()

    result = []
    for r in rows:
        params = {}
        if r["params"]:
            try:
                params = json.loads(r["params"])
            except (ValueError, TypeError):
                params = {}
        result.append({"id": r["id"], "device": r["device_name"], "kind": r["kind"], "params": params})
    return {"commands": result}


@router.post("/commands/{id}/result")
async def command_result(id: str, request: Request, agent_id: str = Depends(require_agent), env: Env = Depends(get_env)):
    body = await json_body(request)
    status = as_enum(field(body, "status"), "status", ("succeeded", "failed"))
    if not status.ok:
        raise http_error(400, status.error)
    result = field(body, "result", default=_MISSING)
    if result is not _MISSING and not isinstance(result, dict):
        raise http_error(400, "result must be an object")
    artifact = _validate_artifact(field(body, "artifact", default=_MISSING))
    if not artifact.ok:
        raise http_error(400, artifact.error)

    if artifact.value is not None:
        cmd = await env.db.prepare(
            "SELECT kind FROM commands WHERE id = ?1 AND agent_id = ?2 AND status = 'claimed'"
        ).bind(id, agent_id).first()
        if not cmd:
            raise http_error(404, "command not found, not yours, or not in 'claimed' state")
        if cmd["kind"] != "sensitive_export":
            raise http_error(400, f"artifact only allowed for sensitive_export, not {cmd['kind']}")

    res = await env.db.prepare(
        "UPDATE commands SET status = ?1, result = ?2, artifact = ?3, finished_at = ?4 "
        "WHERE id = ?5 AND agent_id = ?6 AND status = 'claimed'"
    ).bind(
        status.value,
        json.dumps(result) if result is not _MISSING else None,
        artifact.value,
        now_seconds(),
        id,
        agent_id,
    ).run()
    if res.changes == 0:
        raise http_error(404, "command not found, not yours, or not in 'claimed' state")
    return {"ok": True}


def _validate_artifact(value):
    from schema import V

    if value is _MISSING or value is None:
        return V(True, value=None)
    if not isinstance(value, str):
        return V(False, error="artifact must be a string")
    if len(value) > 5_000_000:
        return V(False, error="artifact must be at most 5,000,000 characters")
    return V(True, value=value)


@router.put("/backups/{device}/{filename}")
async def upload_backup(
    device: str, filename: str, request: Request, agent_id: str = Depends(require_agent), env: Env = Depends(get_env)
):
    claimed_sha = (request.query_params.get("sha256") or "").lower()

    if not BACKUP_NAME_RE.match(filename):
        raise http_error(400, "file_name must match [A-Za-z0-9._-]+\\.backup")
    if claimed_sha and not _SHA_RE.match(claimed_sha):
        raise http_error(400, "sha256 must be 64 lowercase hex chars")

    declared_len_raw = request.headers.get("content-length")
    if declared_len_raw is not None:
        try:
            declared_len = int(declared_len_raw)
            if declared_len > MAX_BACKUP_BYTES:
                raise http_error(413, f"body exceeds {MAX_BACKUP_BYTES} bytes (got {declared_len})")
        except ValueError:
            pass

    dev = await env.db.prepare("SELECT id FROM devices WHERE agent_id = ?1 AND name = ?2").bind(
        agent_id, device
    ).first()
    if not dev:
        raise http_error(404, "device not found for this agent")

    buf = await request.body()
    if len(buf) == 0:
        raise http_error(400, "empty body")
    if len(buf) > MAX_BACKUP_BYTES:
        raise http_error(413, f"body exceeds {MAX_BACKUP_BYTES} bytes (got {len(buf)})")
    computed_sha = hashlib.sha256(buf).hexdigest()
    if claimed_sha and claimed_sha != computed_sha:
        return JSONResponse(
            {"error": "sha256 mismatch", "claimed": claimed_sha, "computed": computed_sha}, status_code=400
        )

    existing = await env.db.prepare(
        "SELECT id, sha256 FROM backup_files WHERE device_id = ?1 AND file_name = ?2"
    ).bind(dev["id"], filename).first()
    if existing:
        if existing["sha256"] and existing["sha256"] != computed_sha:
            return JSONResponse(
                {"error": "sha256 mismatch with existing backup", "existing": existing["sha256"], "computed": computed_sha},
                status_code=409,
            )
        return {"id": existing["id"], "deduped": True}

    r2_key = f"backups/{dev['id']}/{filename}"
    await env.backups.put(
        r2_key,
        buf,
        content_type="application/octet-stream",
        custom_metadata={
            "device_id": dev["id"],
            "device_name": device,
            "agent_id": agent_id,
            "sha256": computed_sha,
        },
    )

    backup_id = new_id("bkp")
    try:
        await env.db.prepare(
            "INSERT INTO backup_files (id, agent_id, device_id, file_name, r2_key, size_bytes, sha256, created_at) "
            "VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)"
        ).bind(backup_id, agent_id, dev["id"], filename, r2_key, len(buf), computed_sha, now_seconds()).run()
    except Exception:  # noqa: BLE001 — UNIQUE race; return the existing row idempotently
        existing_after = await env.db.prepare(
            "SELECT id FROM backup_files WHERE device_id = ?1 AND file_name = ?2"
        ).bind(dev["id"], filename).first()
        if existing_after:
            return {"id": existing_after["id"], "deduped": True}
        raise

    return JSONResponse(
        {"id": backup_id, "r2_key": r2_key, "size_bytes": len(buf), "sha256": computed_sha}, status_code=201
    )


@router.delete("/backups/{id}")
async def delete_backup(id: str, agent_id: str = Depends(require_agent), env: Env = Depends(get_env)):
    row = await env.db.prepare("SELECT r2_key FROM backup_files WHERE id = ?1 AND agent_id = ?2").bind(
        id, agent_id
    ).first()
    if not row:
        raise http_error(404, "backup not found for this agent")
    await env.backups.delete(row["r2_key"])
    await env.db.prepare("DELETE FROM backup_files WHERE id = ?1").bind(id).run()
    return {"ok": True}


@router.get("/config")
async def config(agent_id: str = Depends(require_agent), env: Env = Depends(get_env)):
    rows = await env.db.prepare(
        "SELECT name, address, username, password_env, ssh_key_path, "
        "transport_primary, transport_fallback, api_port, use_tls, ssh_port, "
        "site, role, tags, heartbeat_interval_seconds, grace_seconds, credential_sealed "
        "FROM devices WHERE agent_id = ?1 AND address IS NOT NULL ORDER BY name"
    ).bind(agent_id).all()

    devices = []
    for d in rows:
        tags = None
        if d["tags"]:
            try:
                parsed = json.loads(d["tags"])
                if isinstance(parsed, list):
                    tags = parsed
            except (ValueError, TypeError):
                pass
        entry = {
            "name": d["name"],
            "address": d["address"],
            "transport": {
                "primary": d["transport_primary"],
                "fallback": d["transport_fallback"],
            },
            "api_port": d["api_port"],
            "use_tls": None if d["use_tls"] is None else d["use_tls"] == 1,
            "ssh_port": d["ssh_port"],
            "site": d["site"],
            "role": d["role"],
            "heartbeat_interval_seconds": d["heartbeat_interval_seconds"],
            "grace_seconds": d["grace_seconds"],
        }
        if d["username"] is not None:
            entry["username"] = d["username"]
        if tags is not None:
            entry["tags"] = tags
        if d["credential_sealed"]:
            entry["credential"] = {"kind": "sealed", "blob": d["credential_sealed"]}
        else:
            entry["credential"] = {
                "kind": "ref",
                "password_env": d["password_env"],
                "ssh_key_path": d["ssh_key_path"],
            }
        devices.append(_strip_none(entry))

    agent_row = await env.db.prepare(
        "SELECT git_remote_url, git_remote_branch, git_remote_token_sealed FROM agents WHERE id = ?1"
    ).bind(agent_id).first()

    git = None
    if agent_row and agent_row["git_remote_url"]:
        remote = {
            "url": agent_row["git_remote_url"],
            "branch": agent_row["git_remote_branch"] or "main",
        }
        if agent_row["git_remote_token_sealed"] is not None:
            remote["token_sealed"] = agent_row["git_remote_token_sealed"]
        git = {"remote": remote}

    doc = {"version": 1, "generated_at": now_seconds(), "devices": devices}
    if git is not None:
        doc["git"] = git
    return doc


@router.post("/agent-key")
async def agent_key(request: Request, agent_id: str = Depends(require_agent), env: Env = Depends(get_env)):
    body = await json_body(request)
    public_key = as_string(field(body, "public_key"), "public_key", max=200)
    if not public_key.ok:
        raise http_error(400, public_key.error)
    await env.db.prepare("UPDATE agents SET public_key = ?1 WHERE id = ?2").bind(public_key.value, agent_id).run()
    return {"ok": True}


def _strip_none(d: dict) -> dict:
    """Drop keys whose value is ``None`` so the JSON matches the TS ``?? undefined`` shape
    (omitted rather than ``null``), but keep the nested ``transport``/``credential`` objects."""
    out = {}
    for k, v in d.items():
        if v is None:
            continue
        if isinstance(v, dict) and k in ("transport", "credential"):
            out[k] = {ik: iv for ik, iv in v.items() if iv is not None}
        else:
            out[k] = v
    return out
