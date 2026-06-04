"""Error helper so handlers raise the worker's ``{"error": ...}`` JSON shape.

``http_error(status, message)`` returns an ``HTTPException`` whose ``detail`` is the
message string; ``app`` registers a handler that renders it as ``{"error": detail}``
to preserve the exact response contract the agent + Pro app depend on.
"""

from __future__ import annotations

from fastapi import HTTPException


def http_error(status: int, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail=message)


def is_unique_violation(err: Exception) -> bool:
    """True if ``err`` is a unique-constraint violation, across DB dialects.

    D1 / SQLite surfaces "UNIQUE constraint failed"; Postgres (asyncpg) raises
    ``UniqueViolationError`` / "duplicate key value violates unique constraint".
    """
    if type(err).__name__ == "UniqueViolationError":
        return True
    text = str(err).lower()
    return "unique constraint" in text or "duplicate key" in text
