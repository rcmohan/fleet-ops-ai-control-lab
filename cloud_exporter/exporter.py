"""Copies data from the local stack to a sink (BigQuery tables, and later the agent's topic).

Incidents: signal-correlation enqueues a change notice through its outbox for every timeline
step. For each notice the exporter fetches the current incident (events and timeline included)
and appends it to the `incidents` table. Rows are full snapshots, so a duplicate or late one is
harmless; the `incidents_latest` view keeps the newest.

Evidence: for the steps that bring new facts (detected, recurred), the exporter also gathers
an evidence bundle from the local services (see evidence.py) into the `evidence` table.

Topic: when a topic is configured, each change is also published with the incident and its
evidence inline. That is what will wake the cloud agent; until it exists, leave it unset.

Events: every minute the exporter reads telematics-event's feed from where it stopped and
appends the new events. It starts a few minutes back when it starts, and does not backfill
time the laptop was off.

Context: every few minutes the exporter appends fleets, vehicles and digital-twin states that
changed since the last sync, and all of them once a day, so the 7-day table expiry never drops
a vehicle that has not changed.

The sink loads its buffered rows on its own interval. Events and context feed BigQuery only,
so the default local setup turns them off.

Dashboard: every minute the exporter also rebuilds status.json for the static dashboard (see
dashboard.py). See AGENTIC.md, section 6.1.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fleetops_runtime.services import ServiceClients
from fleetops_runtime.util import content_hash, iso

from .dashboard import Dashboard
from .evidence import build_evidence
from .sinks import Sink

log = logging.getLogger("fleetops.cloud_exporter")

SCHEMA = "fleetops.incident-change.v1"
DEFAULT_TOPIC = "fleetops-incidents"
EVIDENCE_STEPS = frozenset({"detected", "recurred"})
MAX_PAGES = 100
FEED_PAGE = 200
MAX_FEED_PAGES = 50                    # per run; the next run carries on
EVENTS_START_BACK = timedelta(minutes=10)
FULL_RESYNC = timedelta(hours=24)

# table, service, list path, ID field
CONTEXT: tuple[tuple[str, str, str, str], ...] = (
    ("fleets", "fleet-master", "/v1/fleets", "fleetId"),
    ("vehicles", "vehicle-master", "/v1/vehicles", "vehicleId"),
    ("vehicleStates", "digital-twin-context", "/v1/digital-twins/vehicles", "vehicleId"),
)
EVENT_FIELDS = ("eventId", "vehicleId", "eventType", "severity", "regionCode", "observedAt",
                "receivedAt", "payload", "synthetic")


class IncidentGone(Exception):
    """signal-correlation no longer has the incident (for example after a database reset)."""


class Exporter:
    def __init__(
        self,
        sink: Sink,
        services: ServiceClients,
        *,
        topic: str | None = DEFAULT_TOPIC,
        context_interval: float = 300.0,
        events_interval: float = 60.0,
        flush_interval: float = 300.0,
        dashboard: Dashboard | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.dashboard = dashboard
        self.sink, self.services, self.topic = sink, services, topic or None
        self.context_interval, self.events_interval = context_interval, events_interval
        self.flush_interval, self.clock = flush_interval, clock
        self._hashes: dict[str, dict[str, str]] = {}   # table -> ID -> content hash
        self._full_sync_at: datetime | None = None
        self._sync_lock = asyncio.Lock()
        self._events_lock = asyncio.Lock()
        self.events_cursor: str | None = None
        self.incidents_exported = self.events_exported = 0
        self.last_incident: dict[str, Any] | None = None
        self.last_sync: dict[str, Any] | None = None
        self.last_events: dict[str, Any] | None = None
        self.last_flush: dict[str, Any] | None = None
        self.last_error: dict[str, Any] | None = None

    @classmethod
    def from_env(cls, sink: Sink, services: ServiceClients) -> "Exporter":
        def seconds(name: str, default: str) -> float:
            return float(os.environ.get(name, default))

        dashboard_interval = seconds("FLEETOPS_DASHBOARD_INTERVAL_SECONDS", "60")
        return cls(
            sink, services,
            dashboard=Dashboard.from_env(services, dashboard_interval)
            if dashboard_interval > 0 else None,
            topic=os.environ.get("FLEETOPS_EXPORT_INCIDENT_TOPIC", DEFAULT_TOPIC),
            context_interval=seconds("FLEETOPS_EXPORT_CONTEXT_INTERVAL_SECONDS", "300"),
            events_interval=seconds("FLEETOPS_EXPORT_EVENTS_INTERVAL_SECONDS", "60"),
            flush_interval=seconds("FLEETOPS_EXPORT_FLUSH_INTERVAL_SECONDS", "300"),
        )

    def _failed(self, what: str, exc: Exception) -> None:
        self.last_error = {"at": iso(self.clock()), "what": what, "error": str(exc)}

    # --- incidents ---------------------------------------------------------------------------

    async def export_incident_change(self, change: dict[str, Any]) -> dict[str, Any]:
        incident_id = change["incidentId"]
        try:
            incident = await self.services.get(
                "signal-correlation", f"/v1/correlation/incidents/{incident_id}")
            if incident is None:
                raise IncidentGone(incident_id)
            now = self.clock()
            exported_at = iso(now)
            bundle = None
            if change["step"] in EVIDENCE_STEPS:
                bundle = await build_evidence(self.services, incident, now)
                await self.sink.append("evidence", [{
                    "incidentId": incident_id, "vehicleId": incident["vehicleId"],
                    "step": change["step"], "sourceVersion": incident["sourceVersion"],
                    "builtAt": exported_at, "bundle": bundle,
                }])
            await self.sink.append("incidents", [{
                "incidentId": incident_id, "vehicleId": incident["vehicleId"],
                "ruleId": incident.get("ruleId"), "status": incident["status"],
                "riskLevel": incident.get("riskLevel"), "riskScore": incident.get("riskScore"),
                "step": change["step"], "stepId": change["stepId"],
                "sourceVersion": incident["sourceVersion"], "exportedAt": exported_at,
                "incident": incident,
            }])
            if self.topic:
                await self.sink.publish(
                    self.topic,
                    {"schema": SCHEMA, "exportedAt": exported_at, "change": change,
                     "incident": incident, "evidence": bundle},
                    ordering_key=incident_id,
                    attributes={
                        "incidentId": incident_id,
                        "vehicleId": incident["vehicleId"],
                        "step": change["step"],
                        "status": incident["status"],
                        "sourceVersion": str(incident["sourceVersion"]),
                        "dedupeKey": f"{incident_id}:{change['stepId']}",
                        "hasEvidence": "true" if bundle else "false",
                    },
                )
        except Exception as exc:
            self._failed(f"incident {incident_id}", exc)
            raise
        self.incidents_exported += 1
        self.last_incident = {"incidentId": incident_id, "step": change["step"],
                              "status": incident["status"], "exportedAt": exported_at,
                              "evidence": bundle is not None}
        return self.last_incident

    # --- events ------------------------------------------------------------------------------

    async def export_events(self) -> dict[str, Any]:
        """Append the events received since the last run. Returns how many were appended."""
        async with self._events_lock:
            appended = 0
            try:
                for _ in range(MAX_FEED_PAGES):
                    if self.events_cursor:
                        query = {"cursor": self.events_cursor}
                    else:
                        query = {"since": iso(self.clock() - EVENTS_START_BACK)}
                    page = await self.services.get("telematics-event", "/v1/event-feed",
                                                   limit=FEED_PAGE, **query)
                    if page is None:
                        break
                    exported_at = iso(self.clock())
                    rows = [{**{name: event.get(name) for name in EVENT_FIELDS},
                             "exportedAt": exported_at} for event in page["items"]]
                    await self.sink.append("events", rows)
                    self.events_cursor = page["nextCursor"]   # only once the sink has them
                    appended += len(rows)
                    if not page.get("more"):
                        break
            except Exception as exc:
                self._failed("events", exc)
                raise
            finally:
                self.events_exported += appended
            self.last_events = {"at": iso(self.clock()), "appended": appended}
            return self.last_events

    # --- context -----------------------------------------------------------------------------

    async def _list(self, service: str, path: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor = None
        for _ in range(MAX_PAGES):
            page = await self.services.get(service, path, limit=200, cursor=cursor)
            if page is None:
                break
            items += page["items"]
            cursor = page.get("nextCursor")
            if not cursor:
                break
        return items

    async def sync_context(self) -> dict[str, Any]:
        """Append changed context rows (all of them once a day). Returns counts per table."""
        async with self._sync_lock:
            now = self.clock()
            full = self._full_sync_at is None or now - self._full_sync_at >= FULL_RESYNC
            if full:
                self._hashes.clear()
            written: dict[str, int] = {}
            try:
                for table, service, path, id_field in CONTEXT:
                    known = self._hashes.setdefault(table, {})
                    rows, hashes = [], {}
                    synced_at = iso(self.clock())
                    for item in await self._list(service, path):
                        doc_id, digest = item[id_field], content_hash(item)
                        if known.get(doc_id) != digest:
                            rows.append({"id": doc_id, "syncedAt": synced_at, "data": item})
                            hashes[doc_id] = digest
                    await self.sink.append(table, rows)
                    known.update(hashes)   # only once the sink has them
                    written[table] = len(rows)
            except Exception as exc:
                self._failed("context sync", exc)
                raise
            if full:
                self._full_sync_at = now
            self.last_sync = {"at": iso(self.clock()), "full": full, "written": written}
            return self.last_sync

    # --- loading -----------------------------------------------------------------------------

    async def flush(self) -> dict[str, Any]:
        result = await self.sink.flush()
        if result["failed"]:
            self._failed("flush", RuntimeError("; ".join(
                f"{table}: {error}" for table, error in result["failed"].items())))
        self.last_flush = {"at": iso(self.clock()), **result}
        return self.last_flush

    async def _every(self, interval: float, name: str,
                     step: Callable[[], Awaitable[Any]]) -> None:
        while True:
            try:
                await step()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("%s failed", name)
            await asyncio.sleep(interval)

    async def run(self) -> None:
        """Sync context, read events and flush the sink, each on its own interval (0 disables).
        Stopping flushes once more, so a clean shutdown keeps what is buffered."""
        loops = [(self.context_interval, "context sync", self.sync_context),
                 (self.events_interval, "event export", self.export_events),
                 (self.flush_interval, "flush", self.flush)]
        if self.dashboard:
            loops.append((self.dashboard.refresh_seconds, "dashboard", self.dashboard.refresh))
        tasks = [asyncio.create_task(self._every(interval, name, step))
                 for interval, name, step in loops if interval > 0]
        try:
            if tasks:
                await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
                try:
                    await asyncio.shield(self.flush())
                except Exception:
                    log.exception("final flush failed")

    def status(self) -> dict[str, Any]:
        return {
            "sink": self.sink.describe(),
            "topic": self.topic,
            "incidentsExported": self.incidents_exported,
            "lastIncident": self.last_incident,
            "eventsExported": self.events_exported,
            "lastEvents": self.last_events,
            "contextIntervalSeconds": self.context_interval,
            "eventsIntervalSeconds": self.events_interval,
            "flushIntervalSeconds": self.flush_interval,
            "lastContextSync": self.last_sync,
            "lastFlush": self.last_flush,
            "dashboard": self.dashboard.describe() if self.dashboard else None,
            "lastError": self.last_error,
        }
