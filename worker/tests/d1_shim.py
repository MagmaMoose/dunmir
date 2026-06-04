"""In-memory SQLite implementation of the worker's DB interface, for tests.

Mirrors ``test/d1.ts`` from the original TypeScript worker: the tenancy suite runs
the REAL FastAPI app and its real SQL against an in-memory SQLite seeded with two
tenants, so a handler that forgot a ``tenant_id`` filter is caught. This shim
implements the same async surface the production :mod:`d1` wrapper exposes —
``prepare().bind().first()/all()/run()`` and ``batch()``.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Sequence

from d1 import RunResult

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
_PLACEHOLDER_RE = re.compile(r"\?(\d+)")


def _rewrite(sql: str, params: Sequence[Any]) -> tuple[str, list[Any]]:
    """Rewrite D1's numbered ``?N`` placeholders to anonymous ``?`` and expand the
    bound values by occurrence order (a reused ``?1`` binds its value once per use)."""
    values: list[Any] = []

    def repl(m: re.Match[str]) -> str:
        values.append(params[int(m.group(1)) - 1])
        return "?"

    return _PLACEHOLDER_RE.sub(repl, sql), values


class ShimStatement:
    def __init__(self, conn: sqlite3.Connection, sql: str, params: Sequence[Any] = ()):
        self._conn = conn
        self._sql = sql
        self._params = params

    def bind(self, *params: Any) -> "ShimStatement":
        return ShimStatement(self._conn, self._sql, params)

    def _execute(self) -> sqlite3.Cursor:
        sql, values = _rewrite(self._sql, self._params)
        return self._conn.execute(sql, values)

    async def first(self, column: str | None = None):
        cur = self._execute()
        row = cur.fetchone()
        if row is None:
            return None
        d = {k: row[k] for k in row.keys()}
        return d[column] if column is not None else d

    async def all(self) -> list[dict]:
        cur = self._execute()
        return [{k: r[k] for k in r.keys()} for r in cur.fetchall()]

    async def run(self) -> RunResult:
        cur = self._execute()
        self._conn.commit()
        return RunResult(cur.rowcount if cur.rowcount is not None else 0)


class ShimD1:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def prepare(self, sql: str) -> ShimStatement:
        return ShimStatement(self._conn, sql)

    async def batch(self, statements: Sequence[ShimStatement]) -> list[RunResult]:
        out = []
        for s in statements:
            out.append(await s.run())
        return out


class FakeR2:
    """Minimal R2 stub. ``get`` returns ``None`` (the isolation tests never reach a
    positive read), keeping the env representative without storage."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    async def get(self, key: str):
        return None

    async def put(self, key: str, body: bytes, **_: Any) -> None:
        self.objects[key] = body

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


class TestEnv:
    """Duck-typed environment matching the surface handlers use (``db`` / ``backups``
    / ``get``)."""

    def __init__(self, db: ShimD1, vars: dict[str, str] | None = None, backups: Any = None):
        self.db = db
        self.backups = backups if backups is not None else FakeR2()
        self._vars = vars or {}

    def get(self, name: str, default: str | None = None) -> str | None:
        v = self._vars.get(name)
        return v if v is not None else default


def migrated_conn() -> sqlite3.Connection:
    """Fresh in-memory DB with every migration applied, in order."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
        conn.executescript(f.read_text())
    conn.commit()
    return conn


# Stable fixture ids — referenced by the assertions.
class FX:
    tenantA = "tnt_a"
    tenantB = "tnt_b"
    emailA = "alice@a.example"
    emailB = "bob@b.example"
    agentA = "agt_a"
    agentB = "agt_b"
    agentDefault = "agt_def"
    deviceA = "dev_a"
    deviceB = "dev_b"
    cmdA = "cmd_a"
    cmdB = "cmd_b"
    backupA = "bk_a"
    backupB = "bk_b"
    nameAgentA = "agent-ALPHA"
    nameAgentB = "agent-BRAVO"
    nameDeviceA = "rtr-ALPHA"
    nameDeviceB = "rtr-BRAVO"
    nameRouteA = "route-ALPHA"
    nameRouteB = "route-BRAVO"
    fileA = "alpha-secret.backup"
    fileB = "bravo-secret.backup"
    artifactA = "ALPHA-EXPORT-BODY"
    artifactB = "BRAVO-EXPORT-BODY"


def seed_two_tenants(conn: sqlite3.Connection) -> None:
    """Seed two fully-populated tenants (A and B) plus one agent on tnt_default."""
    t = 1_700_000_000
    conn.executescript(
        f"""
        INSERT INTO tenants (id, name, created_at) VALUES
          ('{FX.tenantA}', 'Alpha', {t}),
          ('{FX.tenantB}', 'Bravo', {t});

        INSERT INTO tenant_members (email, tenant_id, created_at) VALUES
          ('{FX.emailA}', '{FX.tenantA}', {t}),
          ('{FX.emailB}', '{FX.tenantB}', {t});

        INSERT INTO agents (id, name, token_hash, created_at, tenant_id) VALUES
          ('{FX.agentA}', '{FX.nameAgentA}', 'hash_a', {t}, '{FX.tenantA}'),
          ('{FX.agentB}', '{FX.nameAgentB}', 'hash_b', {t}, '{FX.tenantB}'),
          ('{FX.agentDefault}', 'agent-DEFAULT', 'hash_def', {t}, 'tnt_default');

        INSERT INTO devices (id, agent_id, name, last_status, created_at) VALUES
          ('{FX.deviceA}', '{FX.agentA}', '{FX.nameDeviceA}', 'ok', {t}),
          ('{FX.deviceB}', '{FX.agentB}', '{FX.nameDeviceB}', 'ok', {t});

        INSERT INTO jobs (id, agent_id, device_id, kind, status, started_at, finished_at, created_at) VALUES
          ('job_a', '{FX.agentA}', '{FX.deviceA}', 'export', 'ok', {t}, {t}, {t}),
          ('job_b', '{FX.agentB}', '{FX.deviceB}', 'export', 'ok', {t}, {t}, {t});

        INSERT INTO commands (id, device_id, agent_id, kind, status, created_at, artifact) VALUES
          ('{FX.cmdA}', '{FX.deviceA}', '{FX.agentA}', 'sensitive_export', 'succeeded', {t}, '{FX.artifactA}'),
          ('{FX.cmdB}', '{FX.deviceB}', '{FX.agentB}', 'sensitive_export', 'succeeded', {t}, '{FX.artifactB}');

        INSERT INTO alert_routes (id, name, kind, url, min_severity, enabled, created_at, tenant_id) VALUES
          ('ar_a', '{FX.nameRouteA}', 'webhook', 'https://alpha.example/hook', 'warning', 1, {t}, '{FX.tenantA}'),
          ('ar_b', '{FX.nameRouteB}', 'webhook', 'https://bravo.example/hook', 'warning', 1, {t}, '{FX.tenantB}');

        INSERT INTO backup_files (id, agent_id, device_id, file_name, r2_key, size_bytes, sha256, created_at) VALUES
          ('{FX.backupA}', '{FX.agentA}', '{FX.deviceA}', '{FX.fileA}', 'backups/{FX.deviceA}/{FX.fileA}', 10, 'sha_a', {t}),
          ('{FX.backupB}', '{FX.agentB}', '{FX.deviceB}', '{FX.fileB}', 'backups/{FX.deviceB}/{FX.fileB}', 10, 'sha_b', {t});
        """
    )
    conn.commit()
