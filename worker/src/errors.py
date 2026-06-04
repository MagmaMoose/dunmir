"""Error helper so handlers raise the worker's ``{"error": ...}`` JSON shape.

``http_error(status, message)`` returns an ``HTTPException`` whose ``detail`` is the
message string; ``app`` registers a handler that renders it as ``{"error": detail}``
to preserve the exact response contract the agent + Pro app depend on.
"""

from __future__ import annotations

from fastapi import HTTPException


def http_error(status: int, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail=message)
