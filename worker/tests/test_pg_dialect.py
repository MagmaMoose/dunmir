"""Unit tests for the Postgres dialect translation (no database required).

These guard the rewrite the Postgres adapter applies to the D1/SQLite handler SQL
on the way to asyncpg: numbered placeholders and ``INSERT OR IGNORE``.
"""

from __future__ import annotations

from pg import translate_migration, translate_query


def test_numbered_placeholders_become_dollar():
    assert translate_query("SELECT * FROM t WHERE a = ?1 AND b = ?2") == "SELECT * FROM t WHERE a = $1 AND b = $2"


def test_reused_placeholder_preserved():
    # A reused ?N maps to the same $N (asyncpg reuses positional args).
    assert translate_query("WHERE x = ?2 OR y = ?2") == "WHERE x = $2 OR y = $2"


def test_insert_or_ignore_becomes_on_conflict_do_nothing():
    out = translate_query("INSERT OR IGNORE INTO tenants (id, name) VALUES (?1, ?2)")
    assert out == "INSERT INTO tenants (id, name) VALUES ($1, $2) ON CONFLICT DO NOTHING"


def test_insert_or_ignore_is_case_insensitive():
    out = translate_query("insert or ignore into t (a) values (?1)")
    assert out.startswith("INSERT INTO t")
    assert out.endswith("ON CONFLICT DO NOTHING")


def test_plain_insert_with_existing_on_conflict_untouched():
    sql = "INSERT INTO users (id, primary_email) VALUES (?1, ?2) ON CONFLICT(primary_email) DO UPDATE SET x = ?3"
    out = translate_query(sql)
    assert out == "INSERT INTO users (id, primary_email) VALUES ($1, $2) ON CONFLICT(primary_email) DO UPDATE SET x = $3"
    assert out.count("ON CONFLICT") == 1  # no spurious DO NOTHING appended


def test_update_returning_placeholders():
    out = translate_query("UPDATE commands SET status='claimed' WHERE id = ?1 RETURNING commands.id")
    assert out == "UPDATE commands SET status='claimed' WHERE id = $1 RETURNING commands.id"


def test_migration_strftime_rewrite():
    out = translate_migration("INSERT INTO tenants (created_at) VALUES (CAST(strftime('%s', 'now') AS INTEGER));")
    assert "strftime" not in out
    assert "extract(epoch from now())" in out


def test_migration_ddl_passthrough():
    ddl = "CREATE TABLE agents (id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE);"
    assert translate_migration(ddl) == ddl
