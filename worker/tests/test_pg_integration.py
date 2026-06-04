"""Postgres integration test — gated on ``DATABASE_URL`` (and asyncpg installed).

Skipped by default so the core CI stays DB-free; the docker-compose / k8s paths and
CI can opt in by exporting ``DATABASE_URL`` to a throwaway Postgres. Exercises the
real :class:`pg.PgDatabase` adapter: migrations, numbered-placeholder binds,
``INSERT OR IGNORE`` semantics, and ``UPDATE … RETURNING``.
"""

from __future__ import annotations

import os
import uuid

import pytest

DATABASE_URL = os.environ.get("DATABASE_URL")
asyncpg = pytest.importorskip("asyncpg")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")


@pytest.fixture
async def pg():
    from migrate import apply_migrations
    from pg import PgDatabase

    await apply_migrations(DATABASE_URL)
    db = await PgDatabase.connect(DATABASE_URL)
    yield db
    await db.close()


async def test_insert_or_ignore_and_returning(pg):
    tnt = f"tnt_{uuid.uuid4().hex[:8]}"
    agent = f"agt_{uuid.uuid4().hex[:8]}"

    await pg.prepare("INSERT OR IGNORE INTO tenants (id, name, created_at) VALUES (?1, ?2, ?3)").bind(
        tnt, "IntegrationOrg", 1
    ).run()
    # Second INSERT OR IGNORE on the same PK is a no-op (0 changes), not an error.
    res = await pg.prepare("INSERT OR IGNORE INTO tenants (id, name, created_at) VALUES (?1, ?2, ?3)").bind(
        tnt, "IntegrationOrg", 1
    ).run()
    assert res.changes == 0

    await pg.prepare(
        "INSERT INTO agents (id, name, token_hash, created_at, tenant_id) VALUES (?1, ?2, ?3, ?4, ?5)"
    ).bind(agent, f"name-{agent}", f"hash-{agent}", 1, tnt).run()

    row = await pg.prepare("SELECT id, name FROM agents WHERE id = ?1").bind(agent).first()
    assert row["id"] == agent

    # UPDATE … RETURNING round-trips through .all().
    returned = await pg.prepare(
        "UPDATE agents SET disabled = 1 WHERE id = ?1 RETURNING id, disabled"
    ).bind(agent).all()
    assert returned and returned[0]["disabled"] == 1


async def test_batch_runs_in_transaction(pg):
    tnt = f"tnt_{uuid.uuid4().hex[:8]}"
    a1 = f"agt_{uuid.uuid4().hex[:8]}"
    await pg.prepare("INSERT OR IGNORE INTO tenants (id, name, created_at) VALUES (?1, ?2, ?3)").bind(
        tnt, "BatchOrg", 1
    ).run()
    await pg.prepare(
        "INSERT INTO agents (id, name, token_hash, created_at, tenant_id) VALUES (?1, ?2, ?3, ?4, ?5)"
    ).bind(a1, f"n-{a1}", f"h-{a1}", 1, tnt).run()

    results = await pg.batch(
        [
            pg.prepare("DELETE FROM devices WHERE agent_id = ?1").bind(a1),
            pg.prepare("DELETE FROM agents WHERE id = ?1 AND tenant_id = ?2").bind(a1, tnt),
        ]
    )
    assert results[1].changes == 1
