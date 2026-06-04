"""R2 (Cloudflare object storage) wrapped in a small async Python interface.

Only the slice the worker uses: ``get`` / ``put`` / ``delete``. The agent uploads
already-encrypted backup bodies; the worker only ever stores and re-streams
ciphertext. ``js`` / ``pyodide`` imports are deferred so the module imports under
plain CPython (tests inject a fake bucket).
"""

from __future__ import annotations

from typing import Any


class R2Object:
    __slots__ = ("_obj",)

    def __init__(self, js_obj: Any):
        self._obj = js_obj

    @property
    def size(self) -> int | None:
        s = self._obj.size
        return int(s) if s is not None else None

    async def bytes(self) -> bytes:
        buf = await self._obj.arrayBuffer()
        return bytes(buf.to_py())


class R2Bucket:
    __slots__ = ("_bucket",)

    def __init__(self, js_bucket: Any):
        self._bucket = js_bucket

    async def get(self, key: str) -> R2Object | None:
        obj = await self._bucket.get(key)
        return R2Object(obj) if obj is not None else None

    async def put(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str | None = None,
        custom_metadata: dict | None = None,
    ) -> None:
        import js
        from pyodide.ffi import to_js

        opts = js.Object.new()
        if content_type is not None:
            http_meta = js.Object.new()
            http_meta.contentType = content_type
            opts.httpMetadata = http_meta
        if custom_metadata is not None:
            opts.customMetadata = to_js(custom_metadata, dict_converter=js.Object.fromEntries)
        # Hand the raw bytes to R2 as a JS Uint8Array.
        await self._bucket.put(key, to_js(body), opts)

    async def delete(self, key: str) -> None:
        await self._bucket.delete(key)
