"""Status monitor: classification, retention, incremental reads, and the HTTP API."""

import httpx
import pytest
from fastapi.testclient import TestClient

from status_monitor.app import build_app
from status_monitor.monitor import Monitor


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


class Services:
    """ready/live behaviour per service, and how often each OpenAPI document was read."""

    def __init__(self) -> None:
        self.ready = {"a": 200, "b": 503, "c": None}  # None: unreachable
        self.version = "1.0.0"
        self.openapi_reads = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        name, path = request.url.host, request.url.path
        if self.ready[name] is None:
            raise httpx.ConnectError("refused", request=request)
        if path == "/health/ready":
            return httpx.Response(self.ready[name], json={"version": self.version})
        if path == "/health/live":
            return httpx.Response(200, json={})
        if path == "/openapi.json":
            self.openapi_reads += 1
            return httpx.Response(200, json={"paths": {
                "/health/ready": {"get": {}}, "/v1/things": {"get": {}, "post": {}},
                "/v1/things/{id}": {"get": {}, "parameters": []},
            }})
        return httpx.Response(404)


def make(services: Services, clock: Clock) -> Monitor:
    return Monitor(("a", "b", "c"), url_for=lambda slug: f"http://{slug}", interval=5,
                   retention=60, transport=httpx.MockTransport(services), clock=clock)


@pytest.mark.anyio
async def test_classifies_and_reads_operations_once_per_version() -> None:
    services, clock = Services(), Clock()
    monitor = make(services, clock)
    await monitor.run_once()
    snapshot = {s["name"]: s for s in monitor.snapshot()["services"]}
    assert [snapshot[n]["status"] for n in "abc"] == ["healthy", "degraded", "down"]
    assert snapshot["a"]["operations"] == 3 and snapshot["a"]["version"] == "1.0.0"
    assert snapshot["b"]["error"] == "HTTP 503" and snapshot["c"]["error"] == "unreachable"
    assert snapshot["a"]["samples"][0][1] is not None and snapshot["c"]["samples"][0][1] is None

    clock.now += 5
    await monitor.run_once()
    assert services.openapi_reads == 1  # same version: not read again
    services.version = "1.1.0"
    clock.now += 5
    await monitor.run_once()
    assert services.openapi_reads == 2
    await monitor.aclose()


@pytest.mark.anyio
async def test_keeps_only_the_retention_window_and_reads_incrementally() -> None:
    services, clock = Services(), Clock()
    monitor = make(services, clock)
    for _ in range(20):  # 100 seconds of checks with a 60-second retention
        await monitor.run_once()
        clock.now += 5
    samples = {s["name"]: s["samples"] for s in monitor.snapshot()["services"]}
    times = [t for t, _, _ in samples["a"]]
    last_check = clock.now - 5
    assert len(times) == 13 and min(times) >= last_check - 60 and times == sorted(times)

    newer = monitor.snapshot(since=times[-3])["services"][0]["samples"]
    assert [t for t, _, _ in newer] == times[-2:]
    await monitor.aclose()


def test_api_serves_the_snapshot() -> None:
    services, clock = Services(), Clock()
    monitor = make(services, clock)
    with TestClient(build_app(monitor, run_background=False)) as client:
        assert client.get("/health/ready").json()["status"] == "ready"
        body = client.get("/v1/status").json()
        assert body["retentionSeconds"] == 60 and body["intervalSeconds"] == 5
        assert [s["status"] for s in body["services"]] == ["pending"] * 3
        assert client.get("/v1/status", params={"since": "x"}).status_code == 422
