from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from mikrotik_minder_agent.config import ConfigError, load_config, parse_config


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "minder.yaml"
    path.write_text(textwrap.dedent(body).strip() + "\n")
    return path


def test_parse_minimal_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINDER_TOKEN", "mtm_test")
    monkeypatch.setenv("CORE_PASSWORD", "pw")
    path = write(
        tmp_path,
        """
        server:
          url: https://minder.example.workers.dev
          agent_token_env: MINDER_TOKEN
        devices:
          - name: core-rtr-01
            address: 10.0.0.1
            username: minder
            password_env: CORE_PASSWORD
        """,
    )

    cfg = load_config(path)
    assert cfg.server.url == "https://minder.example.workers.dev"
    assert cfg.server.agent_token == "mtm_test"
    assert len(cfg.devices) == 1
    dev = cfg.devices[0]
    assert dev.name == "core-rtr-01"
    assert dev.password == "pw"
    assert cfg.defaults.transport.primary == "api"
    assert cfg.defaults.transport.fallback == "ssh"


def test_inline_password_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINDER_TOKEN", "mtm_x")
    cfg = parse_config({
        "server": {"url": "https://x", "agent_token_env": "MINDER_TOKEN"},
        "devices": [
            {"name": "edge", "address": "10.0.0.2", "username": "admin", "password": "literal"},
        ],
    })
    assert cfg.devices[0].password == "literal"


def test_missing_env_var_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_TOKEN", raising=False)
    with pytest.raises(ConfigError, match="MISSING_TOKEN"):
        parse_config({
            "server": {"url": "https://x", "agent_token_env": "MISSING_TOKEN"},
            "devices": [
                {"name": "edge", "address": "10.0.0.2", "username": "admin", "password": "literal"},
            ],
        })


def test_inline_and_env_are_mutually_exclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MTM", "x")
    with pytest.raises(ConfigError, match="mutually exclusive"):
        parse_config({
            "server": {"url": "https://x", "agent_token": "literal", "agent_token_env": "MTM"},
            "devices": [
                {"name": "edge", "address": "10.0.0.2", "username": "admin", "password": "literal"},
            ],
        })


def test_device_needs_some_credential() -> None:
    with pytest.raises(ConfigError, match="password / password_env / ssh_key_path"):
        parse_config({
            "server": {"url": "https://x", "agent_token": "t"},
            "devices": [{"name": "edge", "address": "10.0.0.2", "username": "admin"}],
        })


def test_duplicate_device_names_rejected() -> None:
    with pytest.raises(ConfigError, match="duplicated"):
        parse_config({
            "server": {"url": "https://x", "agent_token": "t"},
            "devices": [
                {"name": "a", "address": "10.0.0.1", "username": "u", "password": "p"},
                {"name": "a", "address": "10.0.0.2", "username": "u", "password": "p"},
            ],
        })


def test_transport_override_per_device() -> None:
    cfg = parse_config({
        "server": {"url": "https://x", "agent_token": "t"},
        "devices": [
            {
                "name": "edge",
                "address": "10.0.0.2",
                "username": "admin",
                "password": "p",
                "transport": {"primary": "ssh", "fallback": None},
            },
        ],
    })
    assert cfg.devices[0].transport is not None
    assert cfg.devices[0].transport.primary == "ssh"
    assert cfg.devices[0].transport.fallback is None
