"""Apply the D1/SQLite migrations to a Postgres database (portable deployment).

Idempotent: applied files are tracked in ``schema_migrations`` and skipped on
re-run, so this is safe to invoke from a container entrypoint on every boot. Only
``strftime('%s','now')`` differs between dialects; :func:`pg.translate_migration`
handles it. The Cloudflare path uses ``wrangler d1 migrations apply`` instead.

Usage:
    DATABASE_URL=postgres://… python -m migrate
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from pg import translate_migration

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


async def apply_migrations(dsn: str) -> list[str]:
    """Apply any unapplied migrations in order. Returns the filenames applied."""
    import asyncpg

    conn = await asyncpg.connect(dsn)
    applied: list[str] = []
    try:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "  filename TEXT PRIMARY KEY,"
            "  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        )
        done = {r["filename"] for r in await conn.fetch("SELECT filename FROM schema_migrations")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in done:
                continue
            async with conn.transaction():
                await conn.execute(translate_migration(path.read_text()))
                await conn.execute("INSERT INTO schema_migrations (filename) VALUES ($1)", path.name)
            applied.append(path.name)
    finally:
        await conn.close()
    return applied


def main() -> None:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is required")
    applied = asyncio.run(apply_migrations(dsn))
    if applied:
        print(f"applied {len(applied)} migration(s): {', '.join(applied)}")
    else:
        print("database is up to date; no migrations applied")


if __name__ == "__main__":
    main()
