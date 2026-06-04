"""Outbound HTTP via the Workers runtime ``fetch`` (alert delivery + JWKS fetch).

Kept behind a tiny module so tests can monkeypatch it without a live network and
so the ``js`` import stays deferred (this module imports cleanly under CPython).
"""

from __future__ import annotations

import json as _json
from typing import Any


class HttpResponse:
    __slots__ = ("status", "ok", "_js")

    def __init__(self, status: int, ok: bool, js_res: Any):
        self.status = status
        self.ok = ok
        self._js = js_res

    async def json(self) -> Any:
        data = await self._js.json()
        return data.to_py() if hasattr(data, "to_py") else data


async def fetch(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: Any = None,
) -> HttpResponse:
    """Perform an outbound request. ``body`` (when not a str) is JSON-encoded."""
    import js
    from pyodide.ffi import to_js

    opts = js.Object.new()
    opts.method = method
    if headers is not None:
        opts.headers = to_js(headers, dict_converter=js.Object.fromEntries)
    if body is not None:
        opts.body = body if isinstance(body, str) else _json.dumps(body)
    res = await js.fetch(url, opts)
    return HttpResponse(int(res.status), bool(res.ok), res)
