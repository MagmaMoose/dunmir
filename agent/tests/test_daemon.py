from __future__ import annotations

from mikrotik_minder_agent.config import AgentConfig, Defaults, DeviceConfig, ServerConfig
from mikrotik_minder_agent.daemon import (
    _STARTUP_STAGGER_MAX_SECONDS,
    _STARTUP_STAGGER_STEP_SECONDS,
    Daemon,
)


def _config(n: int) -> AgentConfig:
    return AgentConfig(
        server=ServerConfig(url="https://x", agent_token="t"),
        defaults=Defaults(),
        devices=tuple(
            DeviceConfig(name=f"rtr-{i:02d}", address=f"10.0.0.{i}", username="u", password="p")
            for i in range(n)
        ),
    )


def test_startup_offsets_are_staggered_per_device() -> None:
    cfg = _config(5)
    daemon = Daemon(cfg)
    offsets = [daemon._state[d.name].startup_offset for d in cfg.devices]
    # Distinct and increasing, first device runs immediately — so a restart can't
    # fire all five devices' exports/backups in the same instant.
    assert offsets == [i * _STARTUP_STAGGER_STEP_SECONDS for i in range(5)]
    assert offsets[0] == 0.0
    assert len(set(offsets)) == 5


def test_startup_offset_is_capped_for_large_fleets() -> None:
    n = int(_STARTUP_STAGGER_MAX_SECONDS // _STARTUP_STAGGER_STEP_SECONDS) + 5
    cfg = _config(n)
    daemon = Daemon(cfg)
    offsets = [daemon._state[d.name].startup_offset for d in cfg.devices]
    assert max(offsets) == _STARTUP_STAGGER_MAX_SECONDS
    assert all(0.0 <= o <= _STARTUP_STAGGER_MAX_SECONDS for o in offsets)
