from __future__ import annotations

from typing import Any

from mikrotik_minder_agent.remoteconfig import build_devices


def _doc(**overrides: Any) -> dict[str, Any]:
    device: dict[str, Any] = {
        "name": "rtr-01",
        "address": "10.0.0.1",
        "username": "minder",
        "transport": {"primary": "api", "fallback": "ssh"},
        "api_port": 8728,
        "use_tls": False,
        "ssh_port": 22,
        "site": "dc1",
        "role": "core",
        "tags": ["prod", "core"],
        "heartbeat_interval_seconds": 180,
        "credential": {"kind": "ref", "password_env": "RTR01_PW"},
    }
    device.update(overrides)
    return {"version": 1, "devices": [device]}


def test_build_devices_resolves_password_ref() -> None:
    devices = build_devices(_doc(), env={"RTR01_PW": "s3cret"})
    assert len(devices) == 1
    d = devices[0]
    assert (d.name, d.address, d.username) == ("rtr-01", "10.0.0.1", "minder")
    assert d.password == "s3cret"
    assert d.ssh_key_path is None
    assert d.transport is not None
    assert (d.transport.primary, d.transport.fallback) == ("api", "ssh")
    assert d.api_port == 8728
    assert d.use_tls is False
    assert d.ssh_port == 22
    assert d.tags == ("prod", "core")
    assert d.heartbeat_interval_seconds == 180


def test_build_devices_skips_unresolved_password() -> None:
    # password_env not present in the environment → device can't connect → skipped.
    assert build_devices(_doc(), env={}) == ()


def test_build_devices_skips_sealed_credentials() -> None:
    doc = _doc(credential={"kind": "sealed", "blob": "ciphertext"})
    assert build_devices(doc, env={"RTR01_PW": "x"}) == ()


def test_build_devices_accepts_ssh_key_ref_without_password() -> None:
    doc = _doc(credential={"kind": "ref", "ssh_key_path": "/keys/rtr"})
    devices = build_devices(doc, env={})
    assert len(devices) == 1
    assert devices[0].ssh_key_path == "/keys/rtr"
    assert devices[0].password is None


def test_build_devices_skips_missing_address() -> None:
    assert build_devices(_doc(address=None), env={"RTR01_PW": "x"}) == ()


def test_build_devices_no_transport_falls_back_to_none() -> None:
    devices = build_devices(_doc(transport={}), env={"RTR01_PW": "x"})
    assert devices[0].transport is None


def test_build_devices_empty_or_absent() -> None:
    assert build_devices({"devices": []}) == ()
    assert build_devices({}) == ()
