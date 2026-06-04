"""Filesystem-backed object storage for the portable deployment.

Cloudflare uses R2 (first-class). When the app runs in Docker / k8s / locally,
encrypted backup bodies live on a mounted volume instead, behind the same async
interface the R2 wrapper exposes (``get`` → object with ``.size`` / ``.bytes()``,
``put``, ``delete``). Bodies are already AES-encrypted by RouterOS, so this only
ever stores ciphertext.

Keys mirror the R2 layout (``backups/<device_id>/<file>``); ``..`` is rejected so a
key can't escape the base directory.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path


class FsObject:
    __slots__ = ("_path",)

    def __init__(self, path: Path):
        self._path = path

    @property
    def size(self) -> int | None:
        try:
            return self._path.stat().st_size
        except OSError:
            return None

    async def bytes(self) -> bytes:
        return await asyncio.to_thread(self._path.read_bytes)


class FilesystemStorage:
    def __init__(self, base_dir: str):
        self._base = Path(base_dir).resolve()
        self._base.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        path = (self._base / key).resolve()
        if not str(path).startswith(str(self._base) + os.sep) and path != self._base:
            raise ValueError(f"invalid storage key: {key!r}")
        return path

    async def get(self, key: str) -> FsObject | None:
        path = self._resolve(key)
        return FsObject(path) if path.is_file() else None

    async def put(self, key: str, body: bytes, *, content_type: str | None = None, custom_metadata: dict | None = None) -> None:
        path = self._resolve(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)

        await asyncio.to_thread(_write)

    async def delete(self, key: str) -> None:
        path = self._resolve(key)

        def _unlink() -> None:
            try:
                path.unlink()
            except FileNotFoundError:
                pass

        await asyncio.to_thread(_unlink)
