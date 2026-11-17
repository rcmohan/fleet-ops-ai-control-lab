"""Checks every service's readiness on a fixed interval and keeps the last hour in memory.

History is lost when the monitor restarts; that is deliberate (no database for a status page).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

log = logging.getLogger("fleetops.status_monitor")

SERVICES = (
    "vehicle-master", "telematics-unit-master", "fleet-master", "maintenance-history",
    "service-provider-master", "vehicle-context-facade", "telematics-event",
    "digital-twin-context", "policy-playbook", "incident-search", "risk-scoring",
    "case-management", "notification", "approval", "audit-observability", "signal-correlation",
)
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def service_url(slug: str) -> str:  # same rule as fleetops_runtime.services.service_url
    env = "FLEETOPS_" + slug.upper().replace("-", "_") + "_URL"
    return os.environ.get(env, f"http://{slug}:8080").rstrip("/")


@dataclass(frozen=True)
class Sample:
    at: float                  # epoch seconds
    status: str                # healthy | degraded | down
    latency_ms: float | None   # readiness round trip; None when not ready
    error: str = ""


@dataclass
class ServiceHistory:
    samples: deque[Sample] = field(default_factory=deque)
    version: str | None = None
    operations: int | None = None


class Monitor:
    def __init__(
        self,
        services: tuple[str, ...] = SERVICES,
        *,
        url_for: Callable[[str], str] = service_url,
        interval: float = 5.0,
        retention: float = 3600.0,
        timeout: float = 3.0,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.services = services
        self.url_for = url_for
        self.interval = interval
        self.retention = retention
        self.clock = clock
        self.client = httpx.AsyncClient(transport=transport, timeout=timeout)
        self.history = {name: ServiceHistory() for name in services}
        self.started_at = clock()

    @classmethod
    def from_env(cls) -> Monitor:
        raw = os.environ.get("FLEETOPS_MONITOR_SERVICES", "")
        services = tuple(item.strip() for item in raw.split(",") if item.strip()) or SERVICES
        return cls(
            services,
            interval=float(os.environ.get("FLEETOPS_MONITOR_INTERVAL_SECONDS", "5")),
            retention=float(os.environ.get("FLEETOPS_MONITOR_RETENTION_SECONDS", "3600")),
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    async def _get(self, url: str) -> tuple[httpx.Response | None, float, str]:
        start = time.perf_counter()
        try:
            response = await self.client.get(url)
        except httpx.TimeoutException:
            return None, 0.0, "timed out"
        except httpx.HTTPError:
            return None, 0.0, "unreachable"
        return response, (time.perf_counter() - start) * 1000, ""

    async def _load_operations(self, name: str) -> None:
        response, _, _ = await self._get(self.url_for(name) + "/openapi.json")
        if response is None or response.status_code != 200:
            return
        try:
            paths = response.json().get("paths", {})
        except ValueError:
            return
        self.history[name].operations = sum(
            len(HTTP_METHODS & set(methods))
            for path, methods in paths.items() if not path.startswith("/health/")
        )

    async def check(self, name: str) -> Sample:
        base = self.url_for(name)
        entry = self.history[name]
        ready, latency, error = await self._get(base + "/health/ready")
        if ready is not None and ready.status_code == 200:
            # Stored as soon as it is timed, so a snapshot never misses an earlier sample.
            sample = Sample(self.clock(), "healthy", round(latency, 2))
            entry.samples.append(sample)
            try:
                version = ready.json().get("version")
            except ValueError:
                version = None
            if entry.operations is None or (version and version != entry.version):
                await self._load_operations(name)
            entry.version = version or entry.version
        else:
            live, _, _ = await self._get(base + "/health/live")
            alive = live is not None and live.status_code == 200
            sample = Sample(self.clock(), "degraded" if alive else "down", None,
                            error or f"HTTP {ready.status_code}")
            entry.samples.append(sample)
        return sample

    def prune(self) -> None:
        cutoff = self.clock() - self.retention
        for entry in self.history.values():
            while entry.samples and entry.samples[0].at < cutoff:
                entry.samples.popleft()

    async def run_once(self) -> None:
        await asyncio.gather(*(self.check(name) for name in self.services))
        self.prune()

    async def run(self) -> None:
        while True:
            started = time.monotonic()
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("status check failed")
            await asyncio.sleep(max(0.0, self.interval - (time.monotonic() - started)))

    def snapshot(self, since: float | None = None) -> dict[str, Any]:
        """Current state and samples newer than `since` (epoch seconds), oldest first.
        Samples are compact [at, latencyMs or null, status] triples."""
        services = []
        for name in self.services:
            entry = self.history[name]
            latest = entry.samples[-1] if entry.samples else None
            services.append({
                "name": name,
                "status": latest.status if latest else "pending",
                "error": latest.error if latest else "",
                "lastCheckedAt": latest.at if latest else None,
                "version": entry.version,
                "operations": entry.operations,
                "samples": [[s.at, s.latency_ms, s.status] for s in entry.samples
                            if since is None or s.at > since],
            })
        return {
            "generatedAt": self.clock(),
            "monitorStartedAt": self.started_at,
            "intervalSeconds": self.interval,
            "retentionSeconds": self.retention,
            "services": services,
        }
