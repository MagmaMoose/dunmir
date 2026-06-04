"""Alert persistence + fan-out delivery (port of notify.ts).

``fire_alert`` writes the alert row, then delivers it to the tenant's configured
webhook/Slack/Discord routes and (when ``SLACK_BOT_TOKEN`` is set) to Slack via
``chat.postMessage``. Outbound HTTP goes through :mod:`outbound` so it can be stubbed.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import outbound
from env import DEFAULT_TENANT_ID
from ids import new_id, now_seconds
from schema import meets_severity

_SEVERITY_COLOR_SLACK = {"info": "#3aa3e3", "warning": "#f2c744", "critical": "#d72631"}
_SEVERITY_COLOR_DISCORD = {"info": 0x3AA3E3, "warning": 0xF2C744, "critical": 0xD72631}
_SEVERITY_EMOJI = {"info": ":white_check_mark:", "warning": ":warning:", "critical": ":rotating_light:"}

# Which Slack channel class an alert lands in, chosen by kind (not severity).
_SLACK_CHANNEL_CLASS = {
    "heartbeat_recovered": "success",
    "backup_succeeded": "success",
    "update_applied": "success",
    "manual": "success",
    "drift_detected": "info",
    "heartbeat_missed": "failure",
    "job_failed": "failure",
    "update_available": "failure",
    "update_failed": "failure",
    "restore_due": "failure",
}


async def fire_alert(env, alert: dict, ctx: Any = None) -> str:
    """Persist an alert and deliver it. Returns the new alert id.

    When ``ctx`` (with ``waitUntil``) is supplied the fan-out runs in the
    background so the request can respond immediately; otherwise it is awaited.
    """
    alert_id = new_id("alert")
    created = now_seconds()
    tenant_id = alert.get("tenant_id") or await _resolve_alert_tenant(env, alert.get("agent_id"))
    await env.db.prepare(
        "INSERT INTO alerts (id, severity, kind, agent_id, device_id, job_id, title, payload, created_at, tenant_id) "
        "VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)"
    ).bind(
        alert_id,
        alert["severity"],
        alert["kind"],
        alert.get("agent_id"),
        alert.get("device_id"),
        alert.get("job_id"),
        alert["title"],
        json.dumps(alert["payload"]),
        created,
        tenant_id,
    ).run()

    stored = {**alert, "id": alert_id, "created_at": created, "tenant_id": tenant_id}
    dispatch = deliver_alert(env, stored)
    if ctx is not None and hasattr(ctx, "waitUntil"):
        ctx.waitUntil(dispatch)
    else:
        await dispatch
    return alert_id


async def deliver_alert(env, alert: dict) -> None:
    routes = await _pick_routes(env, alert)
    work = [_deliver_to_route(env, alert, r) for r in routes]
    if env.get("SLACK_BOT_TOKEN"):
        work.append(_deliver_to_slack_bot(env, alert))
    if not work:
        return
    await asyncio.gather(*work)


async def _resolve_alert_tenant(env, agent_id: str | None) -> str:
    if agent_id:
        row = await env.db.prepare("SELECT tenant_id FROM agents WHERE id = ?1").bind(agent_id).first()
        if row and row["tenant_id"]:
            return row["tenant_id"]
    return DEFAULT_TENANT_ID


async def _pick_routes(env, alert: dict) -> list[dict]:
    rows = await env.db.prepare(
        "SELECT id, name, kind, url, events, min_severity, enabled FROM alert_routes "
        "WHERE enabled = 1 AND tenant_id = ?1"
    ).bind(alert.get("tenant_id") or DEFAULT_TENANT_ID).all()
    out = []
    for r in rows:
        if not meets_severity(alert["severity"], r["min_severity"]):
            continue
        if r["events"]:
            try:
                if alert["kind"] not in json.loads(r["events"]):
                    continue
            except (ValueError, TypeError):
                continue
        out.append(r)
    return out


async def _deliver_to_route(env, alert: dict, route: dict) -> None:
    body = _format_body(alert, route["kind"])
    status = "failed"
    http_status: int | None = None
    error: str | None = None
    try:
        res = await outbound.fetch(
            route["url"],
            method="POST",
            headers={"content-type": "application/json", "user-agent": "mikrotik-minder/0.1"},
            body=body,
        )
        http_status = res.status
        status = "ok" if res.ok else "failed"
        if not res.ok:
            error = f"HTTP {res.status}"
    except Exception as err:  # noqa: BLE001 — delivery failures are recorded, not raised
        error = str(err)

    await env.db.prepare(
        "INSERT INTO alert_deliveries (id, alert_id, route_id, status, http_status, error, delivered_at) "
        "VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)"
    ).bind(new_id("dlv"), alert["id"], route["id"], status, http_status, error, now_seconds()).run()


async def _deliver_to_slack_bot(env, alert: dict) -> None:
    cls = _SLACK_CHANNEL_CLASS.get(alert["kind"], "failure")
    if cls == "success":
        channel = env.get("SLACK_SUCCESS_CHANNEL")
    elif cls == "info":
        channel = env.get("SLACK_INFO_CHANNEL") or env.get("SLACK_FAILURE_CHANNEL")
    else:
        channel = env.get("SLACK_FAILURE_CHANNEL")
    if not channel:
        return
    try:
        res = await outbound.fetch(
            "https://slack.com/api/chat.postMessage",
            method="POST",
            headers={
                "authorization": f"Bearer {env.get('SLACK_BOT_TOKEN')}",
                "content-type": "application/json; charset=utf-8",
            },
            body=_slack_bot_message(alert, channel, env.get("PRO_UI_URL")),
        )
        data = {}
        try:
            data = await res.json()
        except Exception:  # noqa: BLE001
            data = {}
        if not res.ok or not data.get("ok"):
            print("slack chat.postMessage failed", res.status, data.get("error", "(no body)"))
    except Exception as err:  # noqa: BLE001
        print("slack chat.postMessage threw", str(err))


def _format_body(alert: dict, kind: str) -> Any:
    if kind == "slack":
        return _slack_body(alert)
    if kind == "discord":
        return _discord_body(alert)
    return _generic_body(alert)


def _slack_body(alert: dict) -> dict:
    return {
        "text": f"Mikrotik Minder: {alert['kind']}",
        "attachments": [
            {
                "color": _SEVERITY_COLOR_SLACK[alert["severity"]],
                "title": alert["title"],
                "fields": [
                    {"title": "Severity", "value": alert["severity"], "short": True},
                    {"title": "Kind", "value": alert["kind"], "short": True},
                    *_render_fields(alert),
                ],
                "footer": "mikrotik-minder",
                "ts": alert["created_at"],
            }
        ],
    }


def _discord_body(alert: dict) -> dict:
    return {
        "username": "Mikrotik Minder",
        "embeds": [
            {
                "title": alert["title"],
                "color": _SEVERITY_COLOR_DISCORD[alert["severity"]],
                "fields": [
                    {"name": "Severity", "value": alert["severity"], "inline": True},
                    {"name": "Kind", "value": alert["kind"], "inline": True},
                    *(
                        {"name": f["title"], "value": f["value"], "inline": f.get("short", False)}
                        for f in _render_fields(alert)
                    ),
                ],
                "timestamp": datetime.fromtimestamp(alert["created_at"], tz=timezone.utc).isoformat().replace(
                    "+00:00", "Z"
                ),
            }
        ],
    }


def _generic_body(alert: dict) -> dict:
    return {
        "id": alert["id"],
        "severity": alert["severity"],
        "kind": alert["kind"],
        "title": alert["title"],
        "agent_id": alert.get("agent_id"),
        "device_id": alert.get("device_id"),
        "job_id": alert.get("job_id"),
        "payload": alert["payload"],
        "created_at": alert["created_at"],
    }


def _action_label_for(kind: str) -> str:
    if kind == "backup_succeeded":
        return "Download backup"
    if kind == "update_applied":
        return "View update"
    return "Open device"


def _slack_bot_message(alert: dict, channel: str, pro_ui_url: str | None) -> dict:
    detail_lines = "\n".join(f"*{f['title']}:* {f['value']}" for f in _render_fields(alert))
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{_SEVERITY_EMOJI[alert['severity']]} {alert['title']}"[:150],
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Severity:*\n{alert['severity']}"},
                {"type": "mrkdwn", "text": f"*Kind:*\n{alert['kind']}"},
            ],
        },
    ]
    if detail_lines:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": detail_lines[:2900]}})
    if pro_ui_url and alert.get("device_id"):
        from urllib.parse import quote

        button = {
            "type": "button",
            "text": {"type": "plain_text", "text": _action_label_for(alert["kind"]), "emoji": True},
            "url": f"{pro_ui_url.rstrip('/')}/devices/{quote(alert['device_id'], safe='')}",
        }
        if alert["severity"] == "critical":
            button["style"] = "danger"
        blocks.append({"type": "actions", "elements": [button]})
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"mikrotik-minder · alert `{alert['id']}` · "
                    f"<!date^{alert['created_at']}^{{date_short_pretty}} {{time}}|just now>",
                }
            ],
        }
    )
    return {
        "channel": channel,
        "text": f"{alert['severity'].upper()} · {alert['title']}",
        "blocks": blocks,
    }


def _render_fields(alert: dict) -> list[dict]:
    out = []
    for k, v in alert["payload"].items():
        if v is None:
            continue
        s = v if isinstance(v, str) else json.dumps(v)
        if len(s) > 200:
            continue
        out.append({"title": k, "value": s, "short": len(s) < 40})
    return out
