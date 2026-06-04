"""D1 (Cloudflare SQLite) access wrapped in a small async Python interface.

The FastAPI handlers talk to this interface — ``prepare(sql).bind(...).first()/
all()/run()`` and ``batch([...])`` — which mirrors the slice of the D1 client the
original TypeScript worker used. A pure-Python SQLite implementation of the same
interface lives in ``tests/d1_shim.py`` so the business logic is exercised in CI
without the Workers runtime.

All ``js`` / ``pyodide`` imports are deferred into method bodies so this module
imports cleanly under plain CPython (pytest never instantiates these classes).
"""

from __future__ import annotations

from typing import Any, Sequence


class RunResult:
    """Result of a write — ``changes`` is the number of rows affected."""

    __slots__ = ("changes",)

    def __init__(self, changes: int):
        self.changes = changes


def _to_js_param(p: Any):
    # D1 rejects JS ``undefined`` bind values, and pyodide maps Python ``None`` to
    # ``undefined`` — so map ``None`` to an explicit JS ``null``.
    import js

    return js.JSON.parse("null") if p is None else p


def _row_to_dict(js_row: Any) -> dict | None:
    if js_row is None:
        return None
    if hasattr(js_row, "to_py"):
        return js_row.to_py()
    return js_row


class D1Statement:
    __slots__ = ("_stmt",)

    def __init__(self, js_stmt: Any):
        self._stmt = js_stmt

    def bind(self, *params: Any) -> "D1Statement":
        return D1Statement(self._stmt.bind(*[_to_js_param(p) for p in params]))

    async def first(self, column: str | None = None):
        res = await self._stmt.first()
        row = _row_to_dict(res)
        if row is None:
            return None
        return row[column] if column is not None else row

    async def all(self) -> list[dict]:
        res = await self._stmt.all()
        return [_row_to_dict(r) for r in res.results]

    async def run(self) -> RunResult:
        res = await self._stmt.run()
        changes = res.meta.changes
        return RunResult(int(changes) if changes is not None else 0)

    # Exposes the underlying JS statement for `batch`.
    @property
    def js(self) -> Any:
        return self._stmt


class D1Database:
    __slots__ = ("_db",)

    def __init__(self, js_db: Any):
        self._db = js_db

    def prepare(self, sql: str) -> D1Statement:
        return D1Statement(self._db.prepare(sql))

    async def batch(self, statements: Sequence[D1Statement]) -> list[RunResult]:
        import js

        arr = js.Array.new()
        for s in statements:
            arr.push(s.js)
        results = await self._db.batch(arr)
        out: list[RunResult] = []
        for r in results:
            changes = r.meta.changes
            out.append(RunResult(int(changes) if changes is not None else 0))
        return out
