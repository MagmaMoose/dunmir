"""Outbound HTTP (alert delivery + JWKS fetch), portable across runtimes.

On Cloudflare Workers it uses the runtime ``fetch``; as an ordinary process
(Docker / k8s / local) it falls back to ``httpx``. The ``js`` import is attempted
lazily so this module stays importable under CPython, and tests monkeypatch the
callers rather than the network.
"""

from __future__ import annotations

import json as _json
from typing import Any


def _on_workers() -> bool:
    try:
        import js  # noqa: F401

        return True
    except ImportError:
        return False


class HttpResponse:
    __slots__ = ("status", "ok", "_backend", "_raw")

    def __init__(self, status: int, ok: bool, backend: str, raw: Any):
        self.status = status
        self.ok = ok
        self._backend = backend
        self._raw = raw

    async def json(self) -> Any:
        if self._backend == "workers":
            data = await self._raw.json()
            return data.to_py() if hasattr(data, "to_py") else data
        return self._raw.json()


async def fetch(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: Any = None,
) -> HttpResponse:
    """Perform an outbound request. ``body`` (when not a str) is JSON-encoded."""
    if _on_workers():
        return await _fetch_workers(url, method, headers, body)
    return await _fetch_httpx(url, method, headers, body)


async def _fetch_workers(url, method, headers, body) -> HttpResponse:
    import js
    from pyodide.ffi import to_js

    opts = js.Object.new()
    opts.method = method
    if headers is not None:
        opts.headers = to_js(headers, dict_converter=js.Object.fromEntries)
    if body is not None:
        opts.body = body if isinstance(body, str) else _json.dumps(body)
    res = await js.fetch(url, opts)
    return HttpResponse(int(res.status), bool(res.ok), "workers", res)


async def _fetch_httpx(url, method, headers, body) -> HttpResponse:
    import httpx

    content = None if body is None else (body if isinstance(body, str) else _json.dumps(body))
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.request(method, url, headers=headers, content=content)
    return HttpResponse(res.status_code, res.is_success, "httpx", res)
