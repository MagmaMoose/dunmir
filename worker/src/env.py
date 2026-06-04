"""Runtime environment wrapper (port of env.ts).

``Env`` adapts the Cloudflare ``env`` object (bindings + vars + secrets) into the
duck-typed surface the handlers use: ``env.db`` (a :class:`d1.D1Database`),
``env.backups`` (a :class:`r2.R2Bucket`), and ``env.get(name)`` for vars/secrets.
Tests provide their own object with the same surface, so this module is never
instantiated under CPython.
"""

from __future__ import annotations

from typing import Any

from d1 import D1Database
from r2 import R2Bucket

# Single-tenant / self-host default. Every pre-tenancy row belongs here, and with
# MULTI_TENANT off the worker always resolves to it.
DEFAULT_TENANT_ID = "tnt_default"


class Env:
    """Production environment backed by the Cloudflare ``env`` JS object."""

    def __init__(self, raw: Any):
        self._raw = raw
        self.db = D1Database(raw.DB)
        self.backups = R2Bucket(raw.BACKUPS)

    def get(self, name: str, default: str | None = None) -> str | None:
        value = getattr(self._raw, name, None)
        if value is None:
            return default
        return str(value)


def num_env(value: str | None, fallback: int, minimum: int = 1) -> int:
    """Parse a numeric env var, falling back when it isn't an integer ≥ ``minimum``.

    ``minimum`` defaults to 1 (intervals must be > 0); callers that allow 0 — e.g.
    "no grace period" — pass ``minimum=0``. Anything below ``minimum`` falls back.
    """
    if value is None:
        return fallback
    try:
        f = float(value)
    except (TypeError, ValueError):
        return fallback
    if not f.is_integer():
        return fallback
    n = int(f)
    return n if n >= minimum else fallback
