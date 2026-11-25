"""The dashboard's data: one JSON snapshot of the fleet, its incidents and the services.

Every minute the exporter builds `status.json` (`fleetops.status.v1`) from the local services,
writes it next to the other exports, serves it at /v1/dashboard/status.json (the gateway maps
it to /dashboard/status.json, beside the page), and, when a bucket is configured, uploads it to
Cloud Storage, where the same static page renders it. Nothing in the cloud computes anything.

Each section is gathered on its own: a service that is down leaves its section empty and adds
an entry to `errors`, so the page still renders what it can.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import statistics
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fleetops_runtime.services import ServiceClients
from fleetops_runtime.util import iso

log = logging.getLogger("fleetops.cloud_exporter")

SCHEMA = "fleetops.status.v1"
STALE_AFTER = timedelta(minutes=15)   # three missed heartbeats, as in the fleet console
LOW_VOLTAGE = 11.8
VOLTAGE_BINS = (11.4, 11.8, 12.2, 12.6, 13.0)   # edges; below the first and above the last too
INCIDENT_WINDOW = timedelta(hours=24)
OPEN_STATUSES = ("detected", "awaiting_approval", "case_opened")
RECENT_INCIDENTS = 12
CASE_TIMING_SAMPLE = 25    # incidents whose timelines are read to time detection -> case
MAX_ATTENTION = 15
MAX_PAGES = 50
HEALTH = ("healthy", "warning", "critical", "stale")
HEALTH_RANK = {"critical": 0, "warning": 1, "stale": 2, "healthy": 3}


def parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def health_of(state: dict[str, Any] | None, now: datetime) -> str:
    observed = parse((state or {}).get("observedAt"))
    if observed is None or now - observed > STALE_AFTER:
        return "stale"
    reported = state.get("healthState")
    return reported if reported in HEALTH else "warning"


def voltage_bins(voltages: list[float]) -> list[dict[str, Any]]:
    edges = (None, *VOLTAGE_BINS, None)
    bins = []
    for low, high in zip(edges, edges[1:]):
        label = (f"< {high:.1f}" if low is None else f"≥ {low:.1f}" if high is None
                 else f"{low:.1f}–{high:.1f}")
        count = sum(1 for v in voltages
                    if (low is None or v >= low) and (high is None or v < high))
        bins.append({"label": label, "from": low, "to": high, "vehicles": count,
                     "low": high is not None and high <= LOW_VOLTAGE})
    return bins


class Collector:
    def __init__(self, services: ServiceClients) -> None:
        self.services = services
        self.errors: list[dict[str, str]] = []

    async def all(self, service: str, path: str, **params: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor = None
        for _ in range(MAX_PAGES):
            page = await self.services.get(service, path, limit=200, cursor=cursor, **params)
            if page is None:
                break
            items += page["items"]
            cursor = page.get("nextCursor")
            if not cursor:
                break
        return items

    async def section(self, name: str, work: Awaitable[Any], default: Any = None) -> Any:
        try:
            return await work
        except Exception as exc:   # a status page shows what it can
            log.warning("dashboard section %s failed: %s", name, exc)
            self.errors.append({"section": name, "error": str(exc) or type(exc).__name__})
            return default


async def incidents_since(c: Collector, since: datetime) -> list[dict[str, Any]]:
    """Incidents detected since `since`; the list is newest first, so stop at the first older."""
    items: list[dict[str, Any]] = []
    cursor = None
    for _ in range(MAX_PAGES):
        page = await c.services.get("signal-correlation", "/v1/correlation/incidents",
                                    limit=200, cursor=cursor)
        if page is None:
            break
        for item in page["items"]:
            if (parse(item.get("detectedAt")) or since) < since:
                return items
            items.append(item)
        cursor = page.get("nextCursor")
        if not cursor:
            break
    return items


async def open_incidents(c: Collector) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for status in OPEN_STATUSES:
        items += await c.all("signal-correlation", "/v1/correlation/incidents", status=status)
    return items


def minutes_to_case(incident: dict[str, Any]) -> float | None:
    steps = {step["step"]: parse(step["at"]) for step in reversed(incident.get("timeline", []))}
    detected, opened = steps.get("detected"), steps.get("case_opened")
    if detected is None or opened is None:
        return None
    return round((opened - detected).total_seconds() / 60, 1)


def service_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for service in snapshot["services"]:
        samples = service["samples"]
        latencies = [s[1] for s in samples if s[1] is not None]
        rows.append({
            "name": service["name"],
            "status": service["status"],
            "version": service["version"],
            "uptimePct": round(100 * sum(1 for s in samples if s[2] == "healthy")
                               / len(samples), 1) if samples else None,
            "latencyMsP50": round(statistics.median(latencies), 1) if latencies else None,
        })
    return rows


async def build_status(services: ServiceClients, now: datetime,
                       refresh_seconds: float = 60.0) -> dict[str, Any]:
    c = Collector(services)
    since = now - INCIDENT_WINDOW
    vehicles, states, fleets, recent, monitor, open_list = await asyncio.gather(
        c.section("vehicles", c.all("vehicle-master", "/v1/vehicles"), []),
        c.section("vehicleStates", c.all("digital-twin-context", "/v1/digital-twins/vehicles"),
                  []),
        c.section("fleets", c.all("fleet-master", "/v1/fleets"), []),
        c.section("incidents", incidents_since(c, since), []),
        c.section("services", services.get("status-monitor", "/v1/status")),
        c.section("openIncidents", open_incidents(c), []),
    )
    vehicles = [v for v in vehicles if v.get("lifecycleStatus", "active") == "active"]
    state_of = {s["vehicleId"]: s for s in states}
    vehicle_of = {v["vehicleId"]: v for v in vehicles}
    health = {v["vehicleId"]: health_of(state_of.get(v["vehicleId"]), now) for v in vehicles}
    open_by_fleet = Counter(vehicle_of.get(i["vehicleId"], {}).get("fleetId")
                            for i in open_list)

    def counts(ids: list[str]) -> dict[str, int]:
        tally = Counter(health[i] for i in ids)
        return {name: tally[name] for name in HEALTH}

    regions: dict[str, list[str]] = {}
    members: dict[str, list[str]] = {}
    for v in vehicles:
        regions.setdefault(v.get("regionCode") or "unknown", []).append(v["vehicleId"])
        members.setdefault(v["fleetId"], []).append(v["vehicleId"])

    # Timelines for the newest incidents: the recent list and detection -> case timing.
    details = await asyncio.gather(*(
        c.section(f"incident {i['incidentId']}", services.get(
            "signal-correlation", f"/v1/correlation/incidents/{i['incidentId']}"))
        for i in recent[:CASE_TIMING_SAMPLE]))
    detail_of = {d["incidentId"]: d for d in details if d}
    timings = [m for d in detail_of.values() if (m := minutes_to_case(d)) is not None]

    hours = [(now - timedelta(hours=n)).replace(minute=0, second=0, microsecond=0)
             for n in range(23, -1, -1)]
    per_hour = Counter((parse(i["detectedAt"])).replace(minute=0, second=0, microsecond=0)
                       for i in recent if i.get("detectedAt"))

    reporting = [state_of[v]["batteryVoltage"] for v in health
                 if health[v] != "stale" and state_of.get(v, {}).get("batteryVoltage") is not None]
    attention = sorted(
        (v for v in vehicles if health[v["vehicleId"]] != "healthy"),
        key=lambda v: (HEALTH_RANK[health[v["vehicleId"]]],
                       state_of.get(v["vehicleId"], {}).get("batteryVoltage") or 99))
    service_list = service_rows(monitor) if monitor else []
    tally = counts(list(health))

    return {
        "schema": SCHEMA,
        "generatedAt": iso(now),
        "refreshSeconds": refresh_seconds,
        "synthetic": True,
        "summary": {
            "vehicles": len(vehicles),
            **tally,
            "reporting": len(vehicles) - tally["stale"],
            "openIncidents": len(open_list),
            "incidents24h": len(recent),
            "casesOpened24h": sum(1 for i in recent if i.get("caseId")),
            "medianMinutesToCase": round(statistics.median(timings), 1) if timings else None,
            "caseTimingSample": len(timings),
            "servicesHealthy": sum(1 for s in service_list if s["status"] == "healthy"),
            "servicesTotal": len(service_list),
        },
        "regions": [{"regionCode": code, "vehicles": len(ids), **counts(ids)}
                    for code, ids in sorted(regions.items())],
        "battery": {"lowThreshold": LOW_VOLTAGE, "reporting": len(reporting),
                    "bins": voltage_bins(reporting)},
        "incidentsByHour": [{"hour": iso(h), "detected": per_hour[h]} for h in hours],
        "incidentStatus24h": dict(Counter(i["status"] for i in recent).most_common()),
        "recentIncidents": [{
            "incidentId": i["incidentId"],
            "vehicleId": i["vehicleId"],
            "fleetId": vehicle_of.get(i["vehicleId"], {}).get("fleetId"),
            "regionCode": vehicle_of.get(i["vehicleId"], {}).get("regionCode"),
            "ruleId": i.get("ruleId"),
            "status": i["status"],
            "riskLevel": i.get("riskLevel"),
            "riskScore": i.get("riskScore"),
            "policyDecision": i.get("policyDecision"),
            "detectedAt": i.get("detectedAt"),
            "caseId": i.get("caseId"),
            "minutesToCase": minutes_to_case(detail_of[i["incidentId"]])
            if i["incidentId"] in detail_of else None,
            "steps": [s["step"] for s in detail_of.get(i["incidentId"], {}).get("timeline", [])],
        } for i in recent[:RECENT_INCIDENTS]],
        "attention": [{
            "vehicleId": v["vehicleId"],
            "fleetId": v["fleetId"],
            "regionCode": v.get("regionCode"),
            "health": health[v["vehicleId"]],
            "batteryVoltage": state_of.get(v["vehicleId"], {}).get("batteryVoltage"),
            "connectivityState": state_of.get(v["vehicleId"], {}).get("connectivityState"),
            "issues": [x["issue"] for x in state_of.get(v["vehicleId"], {}).get("activeIssues",
                                                                                 [])],
            "observedAt": state_of.get(v["vehicleId"], {}).get("observedAt"),
        } for v in attention[:MAX_ATTENTION]],
        "fleets": sorted(({
            "fleetId": f["fleetId"],
            "customerName": f.get("customerName"),
            "slaLevel": f.get("slaLevel"),
            "vehicles": len(members.get(f["fleetId"], [])),
            **counts(members.get(f["fleetId"], [])),
            "openIncidents": open_by_fleet[f["fleetId"]],
        } for f in fleets), key=lambda f: (-f["openIncidents"], -f["critical"], f["fleetId"])),
        "services": service_list,
        "errors": c.errors,
    }


class GcsUploader:
    """Uploads the snapshot to a Cloud Storage object that browsers must not cache."""

    def __init__(self, bucket: str, name: str = "status.json", client: Any = None) -> None:
        if client is None:
            from google.cloud import storage

            client = storage.Client()
        self.bucket, self.name = bucket, name
        self.blob = client.bucket(bucket).blob(name)
        self.blob.cache_control = "no-cache, max-age=0"

    def upload(self, data: bytes) -> None:
        self.blob.upload_from_string(data, content_type="application/json")


class Dashboard:
    def __init__(self, services: ServiceClients, *, directory: str | Path | None = None,
                 uploader: GcsUploader | None = None, refresh_seconds: float = 60.0,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.services, self.uploader, self.clock = services, uploader, clock
        self.directory = Path(directory) if directory else None
        self.refresh_seconds = refresh_seconds
        self.latest: dict[str, Any] | None = None
        self.last_upload_error: str | None = None
        self._lock = asyncio.Lock()

    @classmethod
    def from_env(cls, services: ServiceClients, refresh_seconds: float) -> "Dashboard":
        bucket = os.environ.get("FLEETOPS_DASHBOARD_BUCKET", "")
        return cls(
            services,
            directory=Path(os.environ.get("FLEETOPS_EXPORT_DIR", ".cloud-export")) / "dashboard",
            uploader=GcsUploader(bucket, os.environ.get("FLEETOPS_DASHBOARD_OBJECT",
                                                        "status.json")) if bucket else None,
            refresh_seconds=refresh_seconds,
        )

    def describe(self) -> dict[str, Any]:
        return {
            "generatedAt": self.latest["generatedAt"] if self.latest else None,
            "errors": len(self.latest["errors"]) if self.latest else None,
            "file": str(self.directory / "status.json") if self.directory else None,
            "bucket": f"gs://{self.uploader.bucket}/{self.uploader.name}"
            if self.uploader else None,
            "lastUploadError": self.last_upload_error,
        }

    async def refresh(self) -> dict[str, Any]:
        async with self._lock:
            status = await build_status(self.services, self.clock(), self.refresh_seconds)
            data = json.dumps(status, separators=(",", ":"), ensure_ascii=False).encode()
            if self.directory:
                self.directory.mkdir(parents=True, exist_ok=True)
                target = self.directory / "status.json"
                temporary = target.with_suffix(".json.tmp")
                temporary.write_bytes(data)
                os.replace(temporary, target)
            self.latest = status
            if self.uploader:
                try:
                    await asyncio.to_thread(self.uploader.upload, data)
                    self.last_upload_error = None
                except Exception as exc:   # the local copy is still current
                    self.last_upload_error = str(exc)
                    raise
            return status
