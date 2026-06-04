"""Shared FastAPI dependencies.

Lives in its own module to keep ``app`` ↔ ``routes`` imports acyclic. Resolves the
environment for both runtimes:

  * Cloudflare Workers — the ASGI shim puts the ``env`` JS object in the request
    scope; we wrap it as :class:`env.Env` (D1 + R2).
  * Standalone (Docker / k8s / local) — the app lifespan builds a
    :class:`env.StandaloneEnv` (Postgres + filesystem) into ``app.state.env``.

Tests override :func:`get_env` via ``app.dependency_overrides`` to inject an
in-memory SQLite-backed environment.
"""

from __future__ import annotations

from fastapi import Request


def get_env(request: Request):
    raw = request.scope.get("env")
    if raw is not None:
        from env import Env

        return Env(raw)
    env = getattr(request.app.state, "env", None)
    if env is None:
        raise RuntimeError(
            "no environment configured — run on Cloudflare (env binding) or set DATABASE_URL"
        )
    return env
