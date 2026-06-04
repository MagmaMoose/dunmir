"""Tests for the data-transfer tool (D1/SQLite ⇄ Postgres).

The SQLite↔SQLite round-trip always runs; the cross-dialect SQLite→Postgres→SQLite
move is gated on ``DATABASE_URL`` (a throwaway Postgres), proving a real database
move carries every table across with identical row counts.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from transfer import TABLES, transfer

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"
T = 1_700_000_000


def _apply_schema(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    for f in sorted(MIGRATIONS.glob("*.sql")):
        conn.executescript(f.read_text())
    conn.commit()
    return conn


def _seed(conn: sqlite3.Connection) -> None:
    conn.executescript(
        f"""
        INSERT INTO tenants (id, name, created_at) VALUES ('tnt_x', 'X', {T});
        INSERT INTO users (id, primary_email, created_at) VALUES ('usr_1', 'a@x.example', {T});
        INSERT INTO agents (id, name, token_hash, created_at, tenant_id)
          VALUES ('agt_1', 'a1', 'h1', {T}, 'tnt_x');
        INSERT INTO devices (id, agent_id, name, last_status, created_at)
          VALUES ('dev_1', 'agt_1', 'rtr-1', 'ok', {T});
        INSERT INTO jobs (id, agent_id, device_id, kind, status, started_at, finished_at, created_at)
          VALUES ('job_1', 'agt_1', 'dev_1', 'backup', 'success', {T}, {T}, {T});
        INSERT INTO commands (id, device_id, agent_id, kind, status, created_at)
          VALUES ('cmd_1', 'dev_1', 'agt_1', 'backup', 'pending', {T});
        INSERT INTO alert_routes (id, name, kind, url, min_severity, enabled, created_at, tenant_id)
          VALUES ('ar_1', 'r1', 'webhook', 'https://x.example/h', 'warning', 1, {T}, 'tnt_x');
        INSERT INTO alerts (id, severity, kind, agent_id, device_id, title, payload, created_at, tenant_id)
          VALUES ('al_1', 'info', 'manual', 'agt_1', 'dev_1', 't', '{{}}', {T}, 'tnt_x');
        INSERT INTO backup_files (id, agent_id, device_id, file_name, r2_key, size_bytes, sha256, created_at)
          VALUES ('bk_1', 'agt_1', 'dev_1', 'f.backup', 'backups/dev_1/f.backup', 5, 's', {T});
        INSERT INTO tenant_members (email, tenant_id, created_at) VALUES ('a@x.example', 'tnt_x', {T});
        INSERT INTO auth_accounts (provider, provider_user_id, user_id, created_at)
          VALUES ('stytch', 'm1', 'usr_1', {T});
        INSERT INTO tenant_memberships (tenant_id, user_id, role, created_at)
          VALUES ('tnt_x', 'usr_1', 'owner', {T});
        """
    )
    conn.commit()


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}


@pytest.mark.asyncio
async def test_sqlite_to_sqlite_roundtrip(tmp_path):
    src_path = str(tmp_path / "src.db")
    dst_path = str(tmp_path / "dst.db")
    src = _apply_schema(src_path)
    _seed(src)
    dst = _apply_schema(dst_path)  # schema only

    await transfer(f"sqlite://{src_path}", f"sqlite://{dst_path}")

    src_counts = _counts(src)
    # Reopen dst to see committed rows.
    dst2 = sqlite3.connect(dst_path)
    for table, n in src_counts.items():
        assert dst2.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == n, table
    # Spot-check content carried over, not just counts.
    assert dst2.execute("SELECT name FROM agents WHERE id='agt_1'").fetchone()[0] == "a1"
    src.close()
    dst.close()
    dst2.close()


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")
async def test_sqlite_to_postgres_to_sqlite(tmp_path):
    import asyncpg

    from migrate import apply_migrations

    dsn = os.environ["DATABASE_URL"]
    await apply_migrations(dsn)

    src_path = str(tmp_path / "src.db")
    back_path = str(tmp_path / "back.db")
    src = _apply_schema(src_path)
    _seed(src)
    src_counts = _counts(src)
    src.close()

    # SQLite (D1) → Postgres, clean.
    await transfer(f"sqlite://{src_path}", dsn, truncate=True)

    conn = await asyncpg.connect(dsn)
    try:
        for table, n in src_counts.items():
            got = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
            assert got == n, f"{table}: pg has {got}, expected {n}"
    finally:
        await conn.close()

    # Postgres → SQLite (D1), round-trip back.
    _apply_schema(back_path).close()
    await transfer(dsn, f"sqlite://{back_path}", truncate=True)
    back = sqlite3.connect(back_path)
    for table, n in src_counts.items():
        assert back.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == n, table
    back.close()
