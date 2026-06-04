"""PostgreSQL adapter for the portable (Docker / k8s / local) deployment.

Cloudflare runs on D1 (first-class). When the FastAPI app runs as an ordinary
process it talks to Postgres instead, through the SAME async DB interface the
handlers use (``prepare().bind().first()/all()/run()`` + ``batch()``). The handler
SQL is written in the D1 / SQLite dialect; :func:`translate_query` rewrites it to
Postgres on the way to the driver:

  * numbered ``?N`` placeholders → ``$N`` (reuse preserved),
  * ``INSERT OR IGNORE INTO`` → ``INSERT INTO … ON CONFLICT DO NOTHING``.

``asyncpg`` is imported lazily so this module stays importable under CPython/pytest
and is never pulled into the Cloudflare (Pyodide) bundle.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

from d1 import RunResult

_PLACEHOLDER_RE = re.compile(r"\?(\d+)")
_INSERT_OR_IGNORE_RE = re.compile(r"^\s*INSERT\s+OR\s+IGNORE\s+INTO", re.IGNORECASE)
_STRFTIME_RE = re.compile(r"strftime\(\s*'%s'\s*,\s*'now'\s*\)", re.IGNORECASE)


def translate_query(sql: str) -> str:
    """Rewrite a D1/SQLite query string to its Postgres equivalent."""
    out = _PLACEHOLDER_RE.sub(lambda m: f"${m.group(1)}", sql)
    if _INSERT_OR_IGNORE_RE.search(out):
        out = _INSERT_OR_IGNORE_RE.sub("INSERT INTO", out, count=1)
        if "ON CONFLICT" not in out.upper():
            out = out.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return out


def translate_migration(sql: str) -> str:
    """Rewrite a SQLite migration's DDL to Postgres (only ``strftime`` differs)."""
    return _STRFTIME_RE.sub("extract(epoch from now())", sql)


def _changes_from_status(status: str) -> int:
    # asyncpg execute() returns e.g. "UPDATE 3" / "INSERT 0 1" / "DELETE 2".
    parts = status.split()
    if parts and parts[-1].isdigit():
        return int(parts[-1])
    return 0


class PgStatement:
    __slots__ = ("_pool", "_sql", "_params")

    def __init__(self, pool: Any, sql: str, params: Sequence[Any] = ()):
        self._pool = pool
        self._sql = sql
        self._params = params

    def bind(self, *params: Any) -> "PgStatement":
        return PgStatement(self._pool, self._sql, params)

    async def first(self, column: str | None = None):
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(translate_query(self._sql), *self._params)
        if row is None:
            return None
        d = dict(row)
        return d[column] if column is not None else d

    async def all(self) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(translate_query(self._sql), *self._params)
        return [dict(r) for r in rows]

    async def run(self) -> RunResult:
        async with self._pool.acquire() as conn:
            status = await conn.execute(translate_query(self._sql), *self._params)
        return RunResult(_changes_from_status(status))


class PgDatabase:
    """Async Postgres database exposing the worker's DB interface (asyncpg pool)."""

    __slots__ = ("_pool",)

    def __init__(self, pool: Any):
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str, *, min_size: int = 1, max_size: int = 10) -> "PgDatabase":
        import asyncpg

        pool = await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size)
        return cls(pool)

    def prepare(self, sql: str) -> PgStatement:
        return PgStatement(self._pool, sql)

    async def batch(self, statements: Sequence[PgStatement]) -> list[RunResult]:
        out: list[RunResult] = []
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for s in statements:
                    status = await conn.execute(translate_query(s._sql), *s._params)
                    out.append(RunResult(_changes_from_status(status)))
        return out

    async def close(self) -> None:
        await self._pool.close()
