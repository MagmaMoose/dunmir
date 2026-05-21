"""HTTP client for the Mikrotik Minder control plane."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from .config import ServerConfig

log = logging.getLogger(__name__)


class MinderError(RuntimeError):
    """Raised when the control plane returns an error or is unreachable."""


@dataclass
class JobReport:
    device: str | None
    kind: str
    status: str          # 'success' | 'warning' | 'failed' | 'skipped'
    started_at: int
    finished_at: int
    summary: str | None = None
    details: dict[str, Any] | None = None


class MinderClient:
    """Thin wrapper around the worker's /v1/ingest endpoints.

    Single retry on 5xx because we want fast paths to recover from transient
    Worker hiccups, but we don't want to mask sustained outages from the operator.
    """

    def __init__(self, server: ServerConfig, *, client: httpx.Client | None = None) -> None:
        self._server = server
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=server.url,
            timeout=server.timeout_seconds,
            headers={
                "authorization": f"Bearer {server.agent_token}",
                "content-type": "application/json",
                "user-agent": "mikrotik-minder-agent/0.0.0",
            },
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> MinderClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # --- Public API ---

    def send_heartbeat(self, device: str, status: str = "ok") -> str:
        """POST a heartbeat. Returns the device id assigned by the server."""
        data = self._post_json("/v1/ingest/heartbeat", {"device": device, "status": status})
        return str(data.get("device_id", ""))

    def send_job(self, job: JobReport) -> str:
        """POST a job report. Returns the job id."""
        body: dict[str, Any] = {
            "kind": job.kind,
            "status": job.status,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
        }
        if job.device is not None:
            body["device"] = job.device
        if job.summary is not None:
            body["summary"] = job.summary
        if job.details is not None:
            body["details"] = job.details
        data = self._post_json("/v1/ingest/jobs", body)
        return str(data.get("job_id", ""))

    # --- Internals ---

    def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in (1, 2):
            try:
                resp = self._client.post(path, json=body)
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt == 1:
                    log.warning("minder %s transport error, retrying once: %s", path, exc)
                    continue
                raise MinderError(f"transport error talking to minder: {exc}") from exc

            if 500 <= resp.status_code < 600 and attempt == 1:
                log.warning("minder %s -> %s, retrying once", path, resp.status_code)
                continue

            if resp.status_code >= 400:
                detail = _safe_error(resp)
                raise MinderError(f"minder {path} returned HTTP {resp.status_code}: {detail}")

            try:
                return resp.json()
            except ValueError as exc:
                raise MinderError(f"minder {path} returned non-JSON body") from exc

        # Unreachable, but mypy/runtime safety.
        raise MinderError(f"minder {path} failed: {last_exc}")


def _safe_error(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict) and "error" in data:
            return str(data["error"])
    except ValueError:
        pass
    body = resp.text or ""
    return body[:200] or "<empty body>"
