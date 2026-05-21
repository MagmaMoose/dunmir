"""SSH transport (paramiko)."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any, ClassVar

from ..config import Defaults, DeviceConfig
from . import ProbeResult, TransportError

log = logging.getLogger(__name__)


class _WarnAcceptPolicy:
    """Accept unknown host keys with a single warning per (host, key-type).

    Strict known-hosts enforcement is on the roadmap; for homelab v1 we prefer
    'works on first connect' over 'silently refuses to reach the router'.
    """

    _seen: ClassVar[set[tuple[str, str]]] = set()

    def missing_host_key(self, client, hostname, key):
        keytype = key.get_name()
        if (hostname, keytype) not in self._seen:
            log.warning(
                "accepting unknown host key for %s (%s) — pin known_hosts in production",
                hostname,
                keytype,
            )
            self._seen.add((hostname, keytype))


class SSHTransport:
    kind = "ssh"

    def __init__(self, device: DeviceConfig, defaults: Defaults) -> None:
        if not device.password and not device.ssh_key_path:
            raise TransportError(
                f"device {device.name}: SSH transport needs password or ssh_key_path"
            )
        self._device = device
        self._defaults = defaults

    @property
    def port(self) -> int:
        return self._device.ssh_port or self._defaults.ssh.port

    @property
    def username(self) -> str:
        return self._device.username or self._defaults.ssh.username or "admin"

    @property
    def _connect_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "hostname": self._device.address,
            "port": self.port,
            "username": self.username,
            "timeout": self._defaults.connect_timeout_seconds,
            "auth_timeout": self._defaults.connect_timeout_seconds,
            "banner_timeout": self._defaults.connect_timeout_seconds,
            "look_for_keys": False,
            "allow_agent": False,
        }
        if self._device.ssh_key_path:
            kwargs["key_filename"] = str(Path(self._device.ssh_key_path).expanduser())
        if self._device.password:
            kwargs["password"] = self._device.password
        return kwargs

    def probe(self) -> ProbeResult:
        paramiko = _import_paramiko()
        start = time.monotonic()
        client = self._open_session(paramiko)
        try:
            identity = self._run_one(client, ":put [/system identity get name]", timeout=5)
            version_text = self._run_one(client, "/system resource print", timeout=5)
            version = self._parse_version(version_text)
        except paramiko.SSHException as exc:
            raise TransportError(f"SSH probe command failed: {exc}") from exc
        finally:
            client.close()
        return ProbeResult(
            kind=self.kind,
            identity=identity,
            version=version,
            latency_ms=int((time.monotonic() - start) * 1000),
        )

    def capture(self, command: str, *, timeout: float | None = None) -> str:
        """Run ``command`` over SSH and return its stdout verbatim (no strip).

        Use for full-output commands like ``/export`` where whitespace matters.
        """
        paramiko = _import_paramiko()
        client = self._open_session(paramiko)
        try:
            t = timeout if timeout is not None else self._defaults.export_timeout_seconds
            _stdin, stdout, stderr = client.exec_command(command, timeout=t)
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace").strip()
            if err and not out.strip():
                raise TransportError(f"SSH command produced stderr only: {err}")
            return out
        except paramiko.SSHException as exc:
            raise TransportError(f"SSH command failed: {exc}") from exc
        finally:
            client.close()

    def pull_file(
        self,
        remote_path: str,
        local_path: Path,
        *,
        timeout: float | None = None,
    ) -> int:
        """SFTP-fetch ``remote_path`` into ``local_path``. Returns bytes pulled."""
        paramiko = _import_paramiko()
        client = self._open_session(paramiko)
        try:
            sftp = client.open_sftp()
        except paramiko.SSHException as exc:
            client.close()
            raise TransportError(f"SFTP open failed: {exc}") from exc
        try:
            if timeout is not None:
                channel = sftp.get_channel()
                if channel is not None:
                    channel.settimeout(timeout)
            sftp.get(remote_path, str(local_path))
        except (paramiko.SSHException, OSError) as exc:
            raise TransportError(f"SFTP get '{remote_path}' failed: {exc}") from exc
        finally:
            sftp.close()
            client.close()
        return local_path.stat().st_size

    def _open_session(self, paramiko):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(_WarnAcceptPolicy())  # type: ignore[arg-type]
        try:
            client.connect(**self._connect_kwargs)
        except (TimeoutError, paramiko.SSHException, OSError) as exc:
            raise TransportError(f"SSH connect failed: {exc}") from exc
        return client

    @staticmethod
    def _run_one(client, command: str, *, timeout: float = 5.0) -> str:
        _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        if err and not out:
            raise TransportError(f"SSH command produced stderr only: {err}")
        return out

    @staticmethod
    def _parse_version(output: str | None) -> str | None:
        if not output:
            return None
        match = re.search(r"version:\s*([^\s]+)", output)
        return match.group(1) if match else None


def _import_paramiko():
    try:
        import paramiko
    except ImportError as exc:  # pragma: no cover
        raise TransportError("paramiko is required for the SSH transport") from exc
    return paramiko
