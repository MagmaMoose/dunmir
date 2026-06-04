"""Cross-tenant isolation suite — the gate before MULTI_TENANT may be enabled.

Runs the REAL FastAPI app (its routers, require_operator, resolve_tenant, and the
actual SQL in every handler) against an in-memory SQLite seeded with two tenants.
A handler that forgot its ``tenant_id`` filter would let one tenant's resource
appear in the other's response — which these assertions catch.
"""

from __future__ import annotations

from conftest import ADMIN_TOKEN, bind
from d1_shim import FX


def call(client, env, path, method="GET", email=None, body=None):
    bind(env)
    headers = {"authorization": f"Bearer {ADMIN_TOKEN}"}
    if email:
        headers["X-Auth-Email"] = email
    return client.request(method, path, headers=headers, json=body)


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) AS cnt FROM {table}").fetchone()["cnt"]


class TestMultiTenantAdminIsolation:
    def test_agents_scoped(self, make_env, client):
        env, _ = make_env()
        a = call(client, env, "/v1/admin/agents", email=FX.emailA).text
        assert FX.nameAgentA in a
        assert FX.nameAgentB not in a
        b = call(client, env, "/v1/admin/agents", email=FX.emailB).text
        assert FX.nameAgentB in b
        assert FX.nameAgentA not in b

    def test_devices_scoped(self, make_env, client):
        env, _ = make_env()
        a = call(client, env, "/v1/admin/devices", email=FX.emailA).text
        assert FX.nameDeviceA in a
        assert FX.nameDeviceB not in a

    def test_alert_routes_scoped(self, make_env, client):
        env, _ = make_env()
        a = call(client, env, "/v1/admin/alert-routes", email=FX.emailA).text
        assert FX.nameRouteA in a
        assert FX.nameRouteB not in a

    def test_backup_listing_scoped(self, make_env, client):
        env, _ = make_env()
        own = call(client, env, f"/v1/admin/devices/{FX.deviceA}/backups", email=FX.emailA)
        assert FX.fileA in own.text
        cross = call(client, env, f"/v1/admin/devices/{FX.deviceA}/backups", email=FX.emailB)
        assert cross.status_code == 200
        assert FX.fileA not in cross.text

    def test_enqueue_cross_tenant_404(self, make_env, client):
        env, conn = make_env()
        before = _count(conn, "commands")
        cross = call(
            client, env, "/v1/admin/commands", method="POST", email=FX.emailA,
            body={"device_id": FX.deviceB, "kind": "backup"},
        )
        assert cross.status_code == 404
        assert _count(conn, "commands") == before
        own = call(
            client, env, "/v1/admin/commands", method="POST", email=FX.emailA,
            body={"device_id": FX.deviceA, "kind": "backup"},
        )
        assert own.status_code == 201
        assert _count(conn, "commands") == before + 1

    def test_artifact_cross_tenant(self, make_env, client):
        env, conn = make_env()
        cross = call(client, env, f"/v1/admin/commands/{FX.cmdB}/artifact", email=FX.emailA)
        assert cross.status_code == 404
        assert FX.artifactB not in cross.text
        row = conn.execute("SELECT artifact FROM commands WHERE id = ?", (FX.cmdB,)).fetchone()
        assert row["artifact"] == FX.artifactB

        own = call(client, env, f"/v1/admin/commands/{FX.cmdA}/artifact", email=FX.emailA)
        assert own.status_code == 200
        assert FX.artifactA in own.text
        again = call(client, env, f"/v1/admin/commands/{FX.cmdA}/artifact", email=FX.emailA)
        assert again.status_code == 410
        purged = conn.execute("SELECT artifact FROM commands WHERE id = ?", (FX.cmdA,)).fetchone()
        assert purged["artifact"] is None

    def test_backup_download_cross_tenant_404(self, make_env, client):
        env, _ = make_env()
        cross = call(client, env, f"/v1/admin/backups/{FX.backupB}/download", email=FX.emailA)
        assert cross.status_code == 404

    def test_operator_without_tenant_denied(self, make_env, client):
        env, _ = make_env()
        res = call(client, env, "/v1/admin/agents", email="ghost@nowhere.example")
        assert res.status_code == 403


class TestSuperadminGating:
    def test_tenant_lifecycle_requires_superadmin(self, make_env, client):
        env, _ = make_env()
        denied = call(
            client, env, "/v1/superadmin/tenants", method="POST", email=FX.emailA, body={"name": "Sneaky"}
        )
        assert denied.status_code == 403
        ok = call(
            client, env, "/v1/superadmin/tenants", method="POST", email="root@root.example", body={"name": "Legit"}
        )
        assert ok.status_code in (200, 201)


class TestSingleTenantInertness:
    def test_resolves_default_without_email(self, make_env, client):
        env, _ = make_env(var_overrides={"MULTI_TENANT": "false"})
        res = call(client, env, "/v1/admin/agents")  # no X-Auth-Email at all
        assert res.status_code == 200
        text = res.text
        assert "agent-DEFAULT" in text
        assert FX.nameAgentA not in text
        assert FX.nameAgentB not in text
