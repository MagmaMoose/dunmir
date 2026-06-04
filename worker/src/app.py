"""FastAPI application for the Mikrotik Minder control plane.

Heartbeat / job ingest, dead-man alerts, command dispatch, and the operator admin
API on Cloudflare Python Workers + D1 + R2. This is the ASGI app the Worker
entrypoint (``entry.py``) serves; the cron handler lives in ``scheduled.py``.
"""

from __future__ import annotations

import traceback

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from routes import admin, ingest, tenants

app = FastAPI(title="mikrotik-minder", redirect_slashes=False)

app.include_router(ingest.router)
app.include_router(admin.router)
# Cross-tenant superadmin (tenant lifecycle); gated by SUPERADMIN_EMAILS.
app.include_router(tenants.router)


@app.exception_handler(StarletteHTTPException)
async def _http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    # Preserve the worker's ``{"error": ...}`` shape. Unmatched routes surface as
    # Starlette's default "Not Found" → normalise to the original "not_found".
    detail = exc.detail
    if exc.status_code == 404 and detail == "Not Found":
        detail = "not_found"
    return JSONResponse({"error": detail}, status_code=exc.status_code)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    print("unhandled", "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    return JSONResponse({"error": "internal_error"}, status_code=500)


# Public liveness probe + a "what is this" landing JSON. No state, no auth.
@app.get("/")
async def landing():
    return {
        "service": "mikrotik-minder",
        "docs": "https://github.com/magmamoose/mikrotik-minder",
        "endpoints": {"ingest": "/v1/ingest/*", "admin": "/v1/admin/*", "health": "/v1/health"},
    }


@app.get("/v1/health")
async def health():
    return {"ok": True, "service": "mikrotik-minder"}
