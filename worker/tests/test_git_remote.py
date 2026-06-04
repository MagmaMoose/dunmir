"""Per-agent offsite git remote: admin set/clear/list + delivery in the agent
config doc (token stays a sealed blob; tenant-scoped)."""

from __future__ import annotations

import pytest

from auth import hash_token
from conftest import ADMIN_TOKEN, bind
from d1_shim import FX

AGENT_TOKEN = "mtm_agent_secret_token"


@pytest.fixture
def env_db(make_env):
    env, conn = make_env()
    # Give agentA a real token hash so we can authenticate as it on /v1/ingest/*.
    conn.execute("UPDATE agents SET token_hash = ? WHERE id = ?", (hash_token(AGENT_TOKEN), FX.agentA))
    conn.commit()
    return env


def admin(client, env, path, method="GET", email=None, body=None):
    bind(env)
    headers = {"authorization": f"Bearer {ADMIN_TOKEN}"}
    if email:
        headers["X-Auth-Email"] = email
    return client.request(method, path, headers=headers, json=body)


def agent_config(client, env):
    bind(env)
    return client.get("/v1/ingest/config", headers={"authorization": f"Bearer {AGENT_TOKEN}"})


def test_set_appears_in_config(env_db, client):
    res = admin(
        client, env_db, f"/v1/admin/agents/{FX.agentA}/git-remote", method="POST", email=FX.emailA,
        body={"url": "https://github.com/platform1/dunmir-configs.git", "branch": "prod", "token_sealed": "SEALEDBLOB=="},
    )
    assert res.status_code == 200
    doc = agent_config(client, env_db).json()
    assert doc["git"]["remote"]["url"] == "https://github.com/platform1/dunmir-configs.git"
    assert doc["git"]["remote"]["branch"] == "prod"
    assert doc["git"]["remote"]["token_sealed"] == "SEALEDBLOB=="


def test_list_does_not_leak_sealed_blob(env_db, client):
    admin(
        client, env_db, f"/v1/admin/agents/{FX.agentA}/git-remote", method="POST", email=FX.emailA,
        body={"url": "https://git.example/cfg.git", "token_sealed": "SECRET=="},
    )
    body = admin(client, env_db, "/v1/admin/agents", email=FX.emailA).text
    assert "https://git.example/cfg.git" in body
    assert "git_remote_has_token" in body
    assert "SECRET==" not in body


def test_clear_when_url_null(env_db, client):
    admin(
        client, env_db, f"/v1/admin/agents/{FX.agentA}/git-remote", method="POST", email=FX.emailA,
        body={"url": "https://git.example/cfg.git", "token_sealed": "X=="},
    )
    cleared = admin(
        client, env_db, f"/v1/admin/agents/{FX.agentA}/git-remote", method="POST", email=FX.emailA, body={"url": None}
    )
    assert cleared.status_code == 200
    doc = agent_config(client, env_db).json()
    assert "git" not in doc


def test_rejects_non_git_url(env_db, client):
    res = admin(
        client, env_db, f"/v1/admin/agents/{FX.agentA}/git-remote", method="POST", email=FX.emailA,
        body={"url": "ftp://nope"},
    )
    assert res.status_code == 400


def test_rejects_http(env_db, client):
    res = admin(
        client, env_db, f"/v1/admin/agents/{FX.agentA}/git-remote", method="POST", email=FX.emailA,
        body={"url": "http://insecure.example/cfg.git"},
    )
    assert res.status_code == 400


def test_empty_body_is_400_not_destructive(env_db, client):
    admin(
        client, env_db, f"/v1/admin/agents/{FX.agentA}/git-remote", method="POST", email=FX.emailA,
        body={"url": "https://git.example/cfg.git", "token_sealed": "BLOB=="},
    )
    res = admin(
        client, env_db, f"/v1/admin/agents/{FX.agentA}/git-remote", method="POST", email=FX.emailA, body={}
    )
    assert res.status_code == 400
    doc = agent_config(client, env_db).json()
    assert doc["git"]["remote"]["url"] == "https://git.example/cfg.git"


def test_tenant_scoped(env_db, client):
    res = admin(
        client, env_db, f"/v1/admin/agents/{FX.agentA}/git-remote", method="POST", email=FX.emailB,
        body={"url": "https://evil.example/x.git"},
    )
    assert res.status_code == 404
    doc = agent_config(client, env_db).json()
    assert "git" not in doc
