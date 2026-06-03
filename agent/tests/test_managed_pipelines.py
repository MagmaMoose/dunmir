"""Zero-config (PVC-backed) export + backup pipelines for control-plane agents."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from mikrotik_minder_agent.config import (
    parse_config,
    with_managed_pipelines,
)


def _remote_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str = ""):
    monkeypatch.setenv("MINDER_TOKEN", "mtm_test")
    raw = textwrap.dedent(
        f"""
        server:
          url: https://api.dunmir.example
          agent_token_env: MINDER_TOKEN
        config_source: remote
        {textwrap.indent(textwrap.dedent(body), "        ")}
        """,
    )
    path = tmp_path / "minder.yaml"
    path.write_text(raw)
    from mikrotik_minder_agent.config import load_config

    return load_config(path)


def test_remote_agent_gets_pvc_pipelines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = tmp_path / "state"
    monkeypatch.setenv("DUNMIR_AGENT_STATE_DIR", str(state))
    cfg = _remote_config(tmp_path, monkeypatch)
    assert cfg.git is None and cfg.backup is None  # nothing configured locally

    managed = with_managed_pipelines(cfg)

    assert managed.git is not None
    assert managed.git.repo == str(state / "configs")
    assert managed.git.remote is None  # offsite remote stays opt-in
    assert managed.backup is not None
    assert managed.backup.dir == str(state / "backups")
    assert managed.backup.password  # auto-generated
    # Scheduled capture + backup are enabled so a new device is covered on a timer.
    assert managed.defaults.export_interval_seconds == 3600
    assert managed.defaults.backup_interval_seconds == 24 * 60 * 60


def test_backup_password_is_persisted_and_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = tmp_path / "state"
    monkeypatch.setenv("DUNMIR_AGENT_STATE_DIR", str(state))
    cfg = _remote_config(tmp_path, monkeypatch)

    first = with_managed_pipelines(cfg).backup.password
    second = with_managed_pipelines(cfg).backup.password
    assert first == second  # same key across restarts
    pw_file = state / "backup-password"
    assert pw_file.read_text().strip() == first
    # RouterOS cannot parse a quote/backslash inside a quoted password argument.
    assert '"' not in first and "\\" not in first


def test_local_mode_is_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORE_PASSWORD", "pw")
    path = tmp_path / "minder.yaml"
    path.write_text(
        textwrap.dedent(
            """
            server:
              url: https://api.dunmir.example
              agent_token: mtm_test
            devices:
              - name: core-rtr-01
                address: 10.0.0.1
                username: minder
                password_env: CORE_PASSWORD
            """,
        ).strip()
        + "\n",
    )
    cfg = parse_config(
        __import__("yaml").safe_load(path.read_text()),
    )
    # Local (homelab) config: omitting git/backup still means "disabled".
    assert with_managed_pipelines(cfg).git is None
    assert with_managed_pipelines(cfg).backup is None


def test_explicit_sections_win(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = tmp_path / "state"
    monkeypatch.setenv("DUNMIR_AGENT_STATE_DIR", str(state))
    monkeypatch.setenv("BACKUP_PW", "explicit-pw")
    cfg = _remote_config(
        tmp_path,
        monkeypatch,
        body="""
        git:
          repo: /custom/configs
        backup:
          dir: /custom/backups
          password_env: BACKUP_PW
        """,
    )
    managed = with_managed_pipelines(cfg)
    assert managed.git.repo == "/custom/configs"
    assert managed.backup.dir == "/custom/backups"
    assert managed.backup.password == "explicit-pw"
    assert not (state / "backup-password").exists()  # no managed key generated


def test_disable_via_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DUNMIR_AGENT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("DUNMIR_AGENT_MANAGED_PIPELINES", "0")
    cfg = _remote_config(tmp_path, monkeypatch)
    managed = with_managed_pipelines(cfg)
    assert managed.git is None and managed.backup is None
