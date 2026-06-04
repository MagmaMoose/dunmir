"""Shared pytest fixtures: build the real FastAPI app over an in-memory SQLite env."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import app
from deps import get_env
from d1_shim import ShimD1, TestEnv, migrated_conn, seed_two_tenants

ADMIN_TOKEN = "mtm_test_admin_token"


@pytest.fixture
def make_env():
    """Factory → (env, conn). Each call gets a fresh seeded two-tenant database."""
    conns = []

    def _make(var_overrides: dict | None = None, seed: bool = True, backups=None):
        conn = migrated_conn()
        if seed:
            seed_two_tenants(conn)
        conns.append(conn)
        base_vars = {
            "ADMIN_TOKEN": ADMIN_TOKEN,
            "MULTI_TENANT": "true",
            "SUPERADMIN_EMAILS": "root@root.example",
            "DEFAULT_HEARTBEAT_INTERVAL_SECONDS": "3600",
            "DEFAULT_GRACE_SECONDS": "600",
        }
        if var_overrides:
            base_vars.update(var_overrides)
        return TestEnv(ShimD1(conn), vars=base_vars, backups=backups), conn

    yield _make
    for c in conns:
        c.close()


@pytest.fixture
def client():
    c = TestClient(app, base_url="https://minder.test", raise_server_exceptions=False)
    yield c
    app.dependency_overrides.clear()


def bind(env: TestEnv) -> None:
    """Point the app's ``get_env`` dependency at this test environment."""
    app.dependency_overrides[get_env] = lambda: env
