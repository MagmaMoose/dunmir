"""Move data between the D1 (SQLite) and Postgres backends — in either direction.

The two backends share one schema (the ``migrations/`` chain), so moving a live
database is a row copy, table by table in FK-safe order. This makes switching
hosting (Cloudflare D1 ⇄ self-hosted Postgres) a single command with no schema
surprises.

Endpoints are given as URLs:
  * ``sqlite:///path/to/db.sqlite`` — a SQLite file. For D1, produce one with
    ``wrangler d1 export <db> --output dump.sql`` then ``sqlite3 db.sqlite < dump.sql``
    (and the reverse with ``wrangler d1 execute <db> --file=…`` to load back).
  * ``postgres://user:pass@host/db`` (``postgresql://`` also accepted).

The destination schema must already exist (run ``python -m migrate`` for Postgres,
or ``wrangler d1 migrations apply`` for D1). Inserts use upsert-ignore semantics, so
re-running is safe and the migration-seeded ``tnt_default`` row never collides.

    # Cloudflare D1  →  Postgres
    python -m transfer sqlite:///d1.sqlite postgresql://minder:minder@localhost/minder
    # Postgres  →  D1 (SQLite file, then load back with wrangler)
    python -m transfer postgresql://… sqlite:///d1.sqlite --truncate
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
from typing import Any, Sequence

# Parent-before-child order so plain inserts satisfy foreign keys. schema_migrations
# is intentionally excluded (it's the Postgres-only migrate bookkeeping table).
TABLES: tuple[str, ...] = (
    "tenants",
    "users",
    "agents",
    "devices",
    "jobs",
    "commands",
    "alert_routes",
    "alerts",
    "alert_deliveries",
    "backup_files",
    "tenant_members",
    "auth_accounts",
    "tenant_memberships",
    "billing_accounts",
    "audit_log",
)


class SqliteBackend:
    scheme = "sqlite"

    def __init__(self, path: str):
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row

    async def columns(self, table: str) -> list[str]:
        cur = self._conn.execute(f"PRAGMA table_info({table})")
        return [r[1] for r in cur.fetchall()]

    async def read(self, table: str) -> list[tuple]:
        cur = self._conn.execute(f"SELECT * FROM {table}")
        return [tuple(r) for r in cur.fetchall()]

    async def truncate(self, tables: Sequence[str]) -> None:
        self._conn.execute("PRAGMA foreign_keys = OFF")
        for t in tables:
            self._conn.execute(f"DELETE FROM {t}")
        self._conn.commit()

    async def write(self, table: str, columns: Sequence[str], rows: Sequence[tuple]) -> int:
        cols = ", ".join(columns)
        placeholders = ", ".join("?" for _ in columns)
        cur = self._conn.executemany(
            f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({placeholders})", rows
        )
        self._conn.commit()
        return cur.rowcount if cur.rowcount is not None else 0

    async def close(self) -> None:
        self._conn.close()


class PostgresBackend:
    scheme = "postgres"

    def __init__(self, conn: Any):
        self._conn = conn

    @classmethod
    async def connect(cls, dsn: str) -> "PostgresBackend":
        import asyncpg

        return cls(await asyncpg.connect(dsn))

    async def columns(self, table: str) -> list[str]:
        rows = await self._conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = $1 ORDER BY ordinal_position",
            table,
        )
        return [r["column_name"] for r in rows]

    async def read(self, table: str) -> list[tuple]:
        rows = await self._conn.fetch(f"SELECT * FROM {table}")
        return [tuple(r) for r in rows]

    async def truncate(self, tables: Sequence[str]) -> None:
        await self._conn.execute(f"TRUNCATE {', '.join(tables)} CASCADE")

    async def write(self, table: str, columns: Sequence[str], rows: Sequence[tuple]) -> int:
        cols = ", ".join(columns)
        placeholders = ", ".join(f"${i + 1}" for i in range(len(columns)))
        await self._conn.executemany(
            f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) ON CONFLICT DO NOTHING", rows
        )
        return len(rows)

    async def close(self) -> None:
        await self._conn.close()


async def _open(url: str):
    if url.startswith("sqlite://"):
        # sqlite:///abs/path → "/abs/path";  sqlite://rel.db → "rel.db"
        return SqliteBackend(url[len("sqlite://"):])
    if url.startswith(("postgres://", "postgresql://")):
        return await PostgresBackend.connect(url)
    raise SystemExit(f"unsupported URL scheme: {url!r} (use sqlite:// or postgres://)")


async def transfer(src_url: str, dst_url: str, *, truncate: bool = False) -> dict[str, int]:
    src = await _open(src_url)
    dst = await _open(dst_url)
    moved: dict[str, int] = {}
    try:
        if truncate:
            await dst.truncate(tuple(reversed(TABLES)))
        for table in TABLES:
            rows = await src.read(table)
            if not rows:
                moved[table] = 0
                continue
            columns = await src.columns(table)
            moved[table] = await dst.write(table, columns, rows)
    finally:
        await src.close()
        await dst.close()
    return moved


def main() -> None:
    parser = argparse.ArgumentParser(description="Copy all rows between D1 (SQLite) and Postgres.")
    parser.add_argument("source", help="sqlite:///path or postgres://…")
    parser.add_argument("dest", help="sqlite:///path or postgres://…")
    parser.add_argument("--truncate", action="store_true", help="clear destination tables first")
    args = parser.parse_args()
    moved = asyncio.run(transfer(args.source, args.dest, truncate=args.truncate))
    total = sum(moved.values())
    for table, n in moved.items():
        if n:
            print(f"  {table}: {n}")
    print(f"transferred {total} row(s) across {sum(1 for v in moved.values() if v)} table(s)")


if __name__ == "__main__":
    main()
