"""Copies what the cloud agent needs from the local stack to a sink.

Incidents: signal-correlation enqueues a change notice through its outbox for every timeline
step. For each notice the exporter fetches the current incident (events and timeline included),
writes it to the `incidents` collection, and publishes it to the incident topic. Messages are
full snapshots, so a duplicate or late one is harmless.

Evidence: for the steps that bring new facts (detected, recurred), the exporter also gathers
an evidence bundle from the local services (see evidence.py) and writes it to the `evidence`
collection before the incident and the message, so an agent woken by the message finds it.

Context: every few minutes the exporter copies fleets, vehicles and digital-twin states to
collections of the same name, rewriting only documents that changed since the last sync.

The message contract is described in AGENTIC.md, section 6.1.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fleetops_runtime.services import ServiceClients
from fleetops_runtime.util import content_hash, iso

from .evidence import build_evidence
from .sinks import Sink

log = logging.getLogger("fleetops.cloud_exporter")

SCHEMA = "fleetops.incident-change.v1"
DEFAULT_TOPIC = "fleetops-incidents"
INCIDENTS = "incidents"
EVIDENCE = "evidence"
EVIDENCE_STEPS = frozenset({"detected", "recurred"})
MAX_PAGES = 100

# collection, service, list path, ID field
CONTEXT: tuple[tuple[str, str, str, str], ...] = (
    ("fleets", "fleet-master", "/v1/fleets", "fleetId"),
    ("vehicles", "vehicle-master", "/v1/vehicles", "vehicleId"),
    ("vehicleStates", "digital-twin-context", "/v1/digital-twins/vehicles", "vehicleId"),
)


class IncidentGone(Exception):
    """signal-correlation no longer has the incident (for example after a database reset)."""


class Exporter:
    def __init__(
        self,
        sink: Sink,
        services: ServiceClients,
        *,
        topic: str = DEFAULT_TOPIC,
        context_interval: float = 300.0,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.sink, self.services, self.topic = sink, services, topic
        self.context_interval, self.clock = context_interval, clock
        self._hashes: dict[str, dict[str, str]] = {}   # collection -> doc ID -> content hash
        self._sync_lock = asyncio.Lock()
        self.incidents_exported = 0
        self.last_incident: dict[str, Any] | None = None
        self.last_sync: dict[str, Any] | None = None
        self.last_error: dict[str, Any] | None = None

    @classmethod
    def from_env(cls, sink: Sink, services: ServiceClients) -> "Exporter":
        return cls(
            sink, services,
            topic=os.environ.get("FLEETOPS_EXPORT_INCIDENT_TOPIC", DEFAULT_TOPIC),
            context_interval=float(os.environ.get("FLEETOPS_EXPORT_CONTEXT_INTERVAL_SECONDS",
                                                  "300")),
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
            evidence_ref = None
            if change["step"] in EVIDENCE_STEPS:
                bundle = await build_evidence(self.services, incident, now)
                await self.sink.put(EVIDENCE, {incident_id: bundle})
                evidence_ref = f"{EVIDENCE}/{incident_id}"
            await self.sink.put(INCIDENTS, {incident_id: {**incident, "exportedAt": exported_at}})
            attributes = {
                "incidentId": incident_id,
                "vehicleId": incident["vehicleId"],
                "step": change["step"],
                "status": incident["status"],
                "sourceVersion": str(incident["sourceVersion"]),
                "dedupeKey": f"{incident_id}:{change['stepId']}",
            }
            if evidence_ref:
                attributes["evidenceRef"] = evidence_ref
            await self.sink.publish(
                self.topic,
                {"schema": SCHEMA, "exportedAt": exported_at, "change": change,
                 "incident": incident, "evidenceRef": evidence_ref},
                ordering_key=incident_id,
                attributes=attributes,
            )
        except Exception as exc:
            self._failed(f"incident {incident_id}", exc)
            raise
        self.incidents_exported += 1
        self.last_incident = {"incidentId": incident_id, "step": change["step"],
                              "status": incident["status"], "exportedAt": exported_at,
                              "evidenceRef": evidence_ref}
        return self.last_incident

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
        """Copy changed context documents. Returns how many were written per collection."""
        async with self._sync_lock:
            written: dict[str, int] = {}
            try:
                for collection, service, path, id_field in CONTEXT:
                    known = self._hashes.setdefault(collection, {})
                    changed, hashes = {}, {}
                    for item in await self._list(service, path):
                        doc_id, digest = item[id_field], content_hash(item)
                        if known.get(doc_id) != digest:
                            changed[doc_id], hashes[doc_id] = item, digest
                    synced_at = iso(self.clock())
                    await self.sink.put(collection, {
                        doc_id: {**item, "syncedAt": synced_at} for doc_id, item in changed.items()
                    })
                    known.update(hashes)   # only once the sink has them
                    written[collection] = len(changed)
            except Exception as exc:
                self._failed("context sync", exc)
                raise
            self.last_sync = {"at": iso(self.clock()), "written": written}
            return self.last_sync

    async def run(self) -> None:
        """Sync context now and then every context_interval seconds (0 disables it)."""
        if self.context_interval <= 0:
            return
        while True:
            try:
                await self.sync_context()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("context sync failed")
            await asyncio.sleep(self.context_interval)

    def status(self) -> dict[str, Any]:
        return {
            "sink": self.sink.describe(),
            "topic": self.topic,
            "incidentsExported": self.incidents_exported,
            "lastIncident": self.last_incident,
            "contextIntervalSeconds": self.context_interval,
            "lastContextSync": self.last_sync,
            "lastError": self.last_error,
        }
