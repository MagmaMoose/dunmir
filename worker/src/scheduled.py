"""Dead-man-alert sweep run by the cron trigger (port of scheduled.ts).

Flips devices to ``down`` once they're past their heartbeat interval + grace and
fires a ``heartbeat_missed`` alert. A race guard makes a heartbeat landing between
the SELECT and UPDATE turn the flip into a no-op, preventing a false alert.
"""

from __future__ import annotations

import asyncio
from typing import Any

from env import num_env
from ids import now_seconds
from notify import fire_alert

# Keep operator audit entries for 90 days, then prune.
AUDIT_RETENTION_SECONDS = 90 * 24 * 60 * 60


async def _prune_audit_log(env, now: int) -> None:
    try:
        await env.db.prepare("DELETE FROM audit_log WHERE created_at < ?1").bind(
            now - AUDIT_RETENTION_SECONDS
        ).run()
    except Exception:  # noqa: BLE001 — audit_log absent (migration 0009 unapplied)
        pass


async def run_scheduled_sweep(env, ctx: Any = None) -> None:
    default_interval = num_env(env.get("DEFAULT_HEARTBEAT_INTERVAL_SECONDS"), 3600)
    # Grace can legitimately be 0 ("alert the moment we're past the interval").
    default_grace = num_env(env.get("DEFAULT_GRACE_SECONDS"), 600, 0)
    now = now_seconds()

    # Housekeeping first, so a later early-return can't skip it.
    await _prune_audit_log(env, now)

    rows = await env.db.prepare(
        "SELECT id, agent_id, name, site, last_seen_at, heartbeat_interval_seconds, grace_seconds "
        "FROM devices WHERE last_status != 'down' AND last_seen_at IS NOT NULL"
    ).all()

    stale = []
    for d in rows:
        interval = d["heartbeat_interval_seconds"] if d["heartbeat_interval_seconds"] is not None else default_interval
        grace = d["grace_seconds"] if d["grace_seconds"] is not None else default_grace
        if d["last_seen_at"] is not None and now - d["last_seen_at"] > interval + grace:
            stale.append(d)

    if not stale:
        return

    lost = []
    for d in stale:
        res = await env.db.prepare(
            "UPDATE devices SET last_status = 'down', last_status_changed_at = ?1 "
            "WHERE id = ?2 AND last_seen_at = ?3 AND last_status != 'down'"
        ).bind(now, d["id"], d["last_seen_at"]).run()
        if res.changes > 0:
            lost.append(d)

    if not lost:
        return

    async def _alert(d: dict) -> None:
        last_seen_ago = now - d["last_seen_at"] if d["last_seen_at"] else None
        await fire_alert(
            env,
            {
                "severity": "critical",
                "kind": "heartbeat_missed",
                "agent_id": d["agent_id"],
                "device_id": d["id"],
                "title": f"{d['name']} missed heartbeat",
                "payload": {
                    "device": d["name"],
                    "site": d["site"],
                    "last_seen_at": d["last_seen_at"],
                    "last_seen_seconds_ago": last_seen_ago,
                    "expected_interval_seconds": d["heartbeat_interval_seconds"]
                    if d["heartbeat_interval_seconds"] is not None
                    else default_interval,
                    "grace_seconds": d["grace_seconds"] if d["grace_seconds"] is not None else default_grace,
                },
            },
            ctx,
        )

    await asyncio.gather(*[_alert(d) for d in lost])
