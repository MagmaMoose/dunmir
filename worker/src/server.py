"""Uvicorn entrypoint for the portable (Docker / k8s / local) deployment.

Serves the same FastAPI app as Cloudflare, backed by Postgres + filesystem storage
(see ``env.StandaloneEnv``, wired in via the app lifespan when ``DATABASE_URL`` is
set). Cloudflare uses ``entry.py`` (the Workers entrypoint) instead.

Usage:
    DATABASE_URL=postgres://… ADMIN_TOKEN=… python -m server
    # or: uvicorn app:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    uvicorn.run(
        "app:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        log_level=os.environ.get("LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
