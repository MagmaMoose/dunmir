from __future__ import annotations

import json

import httpx
import pytest
import respx

from mikrotik_minder_agent.config import ServerConfig
from mikrotik_minder_agent.minder import JobReport, MinderClient, MinderError

SERVER = ServerConfig(url="https://minder.example.workers.dev", agent_token="mtm_test")


@respx.mock
def test_heartbeat_sends_expected_body() -> None:
    response = httpx.Response(200, json={"ok": True, "device_id": "dev_123", "created": True})
    route = respx.post("https://minder.example.workers.dev/v1/ingest/heartbeat").mock(
        return_value=response,
    )
    with MinderClient(SERVER) as client:
        device_id = client.send_heartbeat("core-rtr-01", status="ok")
    assert device_id == "dev_123"
    call = route.calls.last
    assert call.request.headers["authorization"] == "Bearer mtm_test"
    assert call.request.headers["content-type"] == "application/json"
    assert json.loads(call.request.read()) == {"device": "core-rtr-01", "status": "ok"}


@respx.mock
def test_job_includes_optional_fields() -> None:
    route = respx.post("https://minder.example.workers.dev/v1/ingest/jobs").mock(
        return_value=httpx.Response(201, json={"ok": True, "job_id": "job_x"}),
    )
    job = JobReport(
        device="core-rtr-01",
        kind="health_check",
        status="success",
        started_at=1779000000,
        finished_at=1779000005,
        summary="api ok",
        details={"latency_ms": 42},
    )
    with MinderClient(SERVER) as client:
        assert client.send_job(job) == "job_x"
    body = json.loads(route.calls.last.request.read())
    assert body["summary"] == "api ok"
    assert body["details"] == {"latency_ms": 42}
    assert body["device"] == "core-rtr-01"
    assert body["kind"] == "health_check"
    assert body["status"] == "success"


@respx.mock
def test_5xx_retried_once_then_succeeds() -> None:
    route = respx.post("https://minder.example.workers.dev/v1/ingest/heartbeat").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, json={"ok": True, "device_id": "dev_x"}),
        ],
    )
    with MinderClient(SERVER) as client:
        client.send_heartbeat("dev")
    assert route.call_count == 2


@respx.mock
def test_4xx_is_immediate_failure_with_useful_message() -> None:
    respx.post("https://minder.example.workers.dev/v1/ingest/heartbeat").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"}),
    )
    with MinderClient(SERVER) as client, pytest.raises(MinderError, match="unauthorized"):
        client.send_heartbeat("dev")
