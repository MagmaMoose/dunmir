"""Request-body helpers shared by the route modules."""

from __future__ import annotations

from typing import Any

from fastapi import Request

# Distinguishes a missing key from an explicit ``null`` (matters where omitting a
# field must keep the existing value but ``null`` must clear it).
MISSING: Any = object()


async def json_body(request: Request) -> Any:
    """Parsed JSON body, or ``None`` when absent/malformed (mirrors ``.catch(()=>null)``)."""
    try:
        return await request.json()
    except Exception:  # noqa: BLE001
        return None


def field(body: Any, key: str, default: Any = None) -> Any:
    """``body?.key`` — the value, or ``default`` when the body isn't an object."""
    return body.get(key, default) if isinstance(body, dict) else default
