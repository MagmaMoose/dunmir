"""Shared FastAPI dependencies.

Lives in its own module to keep ``app`` ↔ ``routes`` imports acyclic. Tests
override :func:`get_env` via ``app.dependency_overrides`` to inject an in-memory
SQLite-backed environment.
"""

from __future__ import annotations

from fastapi import Request

from env import Env


def get_env(request: Request) -> Env:
    # The Workers ASGI shim places the Cloudflare ``env`` object in the ASGI scope.
    return Env(request.scope["env"])
