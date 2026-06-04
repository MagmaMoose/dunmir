"""Lightweight runtime validation (port of schema.ts).

Dependency-free request-body validators returning a tiny result object so the
FastAPI handlers can mirror the worker's original ``{ ok, value | error }`` flow
exactly (including which error string is returned for which field).
"""

from __future__ import annotations

import re
from typing import Any, Sequence


class V:
    """A validation result: ``ok`` with ``value``, or not-ok with ``error``."""

    __slots__ = ("ok", "value", "error")

    def __init__(self, ok: bool, value: Any = None, error: str | None = None):
        self.ok = ok
        self.value = value
        self.error = error


def _ok(value: Any) -> V:
    return V(True, value=value)


def _err(message: str) -> V:
    return V(False, error=message)


def as_string(v: Any, field: str, *, max: int | None = None, pattern: re.Pattern[str] | str | None = None) -> V:
    if not isinstance(v, str):
        return _err(f"{field} must be a string")
    trimmed = v.strip()
    if len(trimmed) == 0:
        return _err(f"{field} is required")
    if max and len(trimmed) > max:
        return _err(f"{field} exceeds {max} chars")
    if pattern is not None:
        rx = re.compile(pattern) if isinstance(pattern, str) else pattern
        if not rx.search(trimmed):
            return _err(f"{field} format invalid")
    return _ok(trimmed)


def as_optional_string(v: Any, field: str, *, max: int | None = None) -> V:
    if v is None or v == "":
        return _ok(None)
    return as_string(v, field, max=max)


def as_int(v: Any, field: str, *, min: int | None = None, max: int | None = None) -> V:
    # JSON booleans are not integers (mirrors TS, where typeof bool !== number path).
    if isinstance(v, bool):
        return _err(f"{field} must be an integer")
    n: int
    if isinstance(v, int):
        n = v
    elif isinstance(v, float):
        if not v.is_integer():
            return _err(f"{field} must be an integer")
        n = int(v)
    elif isinstance(v, str):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return _err(f"{field} must be an integer")
        if not f.is_integer():
            return _err(f"{field} must be an integer")
        n = int(f)
    else:
        return _err(f"{field} must be an integer")
    if min is not None and n < min:
        return _err(f"{field} must be >= {min}")
    if max is not None and n > max:
        return _err(f"{field} must be <= {max}")
    return _ok(n)


def as_optional_int(v: Any, field: str, *, min: int | None = None, max: int | None = None) -> V:
    if v is None:
        return _ok(None)
    return as_int(v, field, min=min, max=max)


def as_enum(v: Any, field: str, values: Sequence[str]) -> V:
    if not isinstance(v, str) or v not in values:
        return _err(f"{field} must be one of: {', '.join(values)}")
    return _ok(v)


def as_optional_enum(v: Any, field: str, values: Sequence[str]) -> V:
    if v is None or v == "":
        return _ok(None)
    return as_enum(v, field, values)


def as_string_array(v: Any, field: str) -> V:
    if v is None:
        return _ok(None)
    if not isinstance(v, list):
        return _err(f"{field} must be an array")
    for item in v:
        if not isinstance(item, str):
            return _err(f"{field} must be an array of strings")
    return _ok(v)


def as_optional_bool(v: Any, field: str) -> V:
    if v is None:
        return _ok(None)
    if not isinstance(v, bool):
        return _err(f"{field} must be a boolean")
    return _ok(v)


# Device connection transports (control-plane-managed config).
TRANSPORTS = ("api", "ssh")

JOB_KINDS = (
    "backup",
    "export",
    "drift",
    "update_check",
    "update_apply",
    "firmware_align",
    "health_check",
    "restore_validate",
    "inventory_sync",
)

JOB_STATUSES = ("success", "warning", "failed", "skipped")

DEVICE_STATUSES = ("unknown", "ok", "degraded", "down")

ROUTE_KINDS = ("webhook", "slack", "discord")

SEVERITIES = ("info", "warning", "critical")

ALERT_KINDS = (
    "heartbeat_missed",
    "heartbeat_recovered",
    "job_failed",
    "drift_detected",
    "update_available",
    "update_failed",
    "backup_succeeded",
    "update_applied",
    "restore_due",
    "manual",
)

# Command dispatch — operator-triggered actions the agent can be asked to run.
# `sensitive_export` is an /export WITHOUT hide-sensitive (passwords/keys).
COMMAND_KINDS = ("backup", "export", "update_apply", "sensitive_export")
COMMAND_STATUSES = ("pending", "claimed", "succeeded", "failed", "expired")


def severity_rank(s: str) -> int:
    return 0 if s == "info" else 1 if s == "warning" else 2


def meets_severity(s: str, minimum: str) -> bool:
    return severity_rank(s) >= severity_rank(minimum)
