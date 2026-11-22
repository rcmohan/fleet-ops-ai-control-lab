"""Evidence bundle: gathered sections, deterministic features, citations, gaps and limits."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from cloud_exporter import evidence
from cloud_exporter.evidence import SCHEMA, build_evidence
from cloud_exporter.exporter import Exporter
from cloud_exporter.sinks import FileSink
from fleetops_runtime.errors import DependencyUnavailable
from fleetops_runtime.services import ServiceClients

NOW = datetime(2026, 11, 22, 9, 0, tzinfo=UTC)


def at(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


def event(event_id, kind, minutes_ago, vehicle="veh_1", region="us-east", **payload):
    return {"eventId": event_id, "vehicleId": vehicle, "eventType": kind,
            "severity": "warning", "regionCode": region, "observedAt": at(minutes_ago),
            "payload": payload}


INCIDENT = {
    "incidentId": "inc_1", "vehicleId": "veh_1", "status": "detected", "sourceVersion": 1,
    "firstObservedAt": at(20), "lastObservedAt": at(11),
    "symptoms": ["diagnostic_failure", "dtc_p0562", "low_voltage", "missed_heartbeat"],
    "caseEventType": "battery_voltage",
    "events": [
        {**event("evt_t1", "battery_voltage", 20, voltage=11.4), "role": "trigger"},
        {**event("evt_t2", "heartbeat_missed", 15), "role": "trigger"},
        {**event("evt_t3", "diagnostic_failure", 11, dtcCode="P0562"), "role": "trigger"},
    ],
    "timeline": [],
}


def vehicle_events() -> list[dict]:
    """Six hours of a sagging battery among routine traffic, newest first (as the API)."""
    items = []
    for n in range(25):   # every 15 minutes, 12.4 V down to 11.4 V
        items.append(event(f"evt_b{n:02d}", "battery_voltage", 360 - 15 * n,
                           voltage=round(12.4 - n / 24, 2)))
    for n in range(72):
        items.append(event(f"evt_h{n:02d}", "heartbeat", 360 - 5 * n))
        items.append(event(f"evt_l{n:02d}", "location", 360 - 5 * n, latitude=40.7))
    items.append(event("evt_t2", "heartbeat_missed", 15))
    items.append(event("evt_t3", "diagnostic_failure", 11, dtcCode="P0562"))
    return sorted(items, key=lambda e: e["observedAt"], reverse=True)


class Services:
    def __init__(self) -> None:
        self.missing: set[str] = set()      # paths that answer 404
        self.refused: set[str] = set()      # paths that answer 403
        self.down: set[str] = set()         # hosts that refuse connections
        self.unavailable_dependencies: list[str] = []
        self.search_bodies: list[dict] = []
        self.events = vehicle_events()

    def page(self, items, request, size=200):
        start = int(request.url.params.get("cursor") or 0)
        more = start + size < len(items)
        return {"items": items[start:start + size],
                "nextCursor": str(start + size) if more else ""}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        host, path, params = request.url.host, request.url.path, request.url.params
        if host in self.down:
            raise httpx.ConnectError("refused", request=request)
        if path in self.missing:
            return httpx.Response(404)
        if path in self.refused:
            return httpx.Response(403, json={"detail": {"code": "FORBIDDEN"}})
        return httpx.Response(200, json=self.answer(host, path, params, request))

    def answer(self, host, path, params, request):
        if path == "/v1/vehicle-context/veh_1":
            return {"vehicleId": "veh_1",
                    "profile": {"vehicleId": "veh_1", "fleetId": "flt_1",
                                "telematicsUnitId": "tcu_1", "regionCode": "us-east"},
                    "operationalState": {"healthState": "warning"},
                    "unavailableDependencies": self.unavailable_dependencies}
        if path == "/v1/telematics-units/tcu_1":
            return {"unitId": "tcu_1", "firmwareVersion": "3.4.1", "hardwareModel": "NX-5G"}
        if path == "/v1/fleets/flt_1":
            return {"fleetId": "flt_1", "customerName": "Northstar", "priorityLevel": "high"}
        if path == "/v1/fleets/flt_1/sla":
            return {"fleetId": "flt_1", "slaLevel": "mission_critical",
                    "responseTargetMinutes": 30}
        if path == "/v1/fleets/flt_1/contract":
            return {"fleetId": "flt_1", "contractTier": "enterprise"}
        if path == "/v1/digital-twins/fleets/flt_1":
            return {"fleetId": "flt_1", "vehicleCount": 40, "warningVehicleCount": 3}
        if path == "/v1/digital-twins/events/evt_t3/downstream-impact":
            return {"eventId": "evt_t3", "affectedFleetIds": ["flt_1"], "riskLevel": "medium"}
        if path == "/v1/vehicles/veh_1/active-alerts":
            return {"vehicleId": "veh_1", "alerts": [
                {"alertId": "al_1", "alertType": "battery_voltage", "eventId": "evt_t1"}]}
        if path == "/v1/vehicles/veh_1/maintenance-records":
            return {"items": [
                {"maintenanceId": "mnt_old", "serviceStatus": "completed",
                 "openedAt": at(200 * 1440), "completedAt": at(200 * 1440 - 60),
                 "summary": "Battery replaced", "resolution": "New battery"},
                {"maintenanceId": "mnt_new", "serviceStatus": "completed",
                 "openedAt": at(30 * 1440), "completedAt": at(30 * 1440),
                 "summary": "Scheduled inspection", "resolution": "No defects found"},
            ], "nextCursor": ""}
        if path == "/v1/vehicles/veh_1/events":
            return self.page(self.events, request)
        if path == "/v1/events":
            kind = params["event_type"]
            vehicles = {"connectivity_lost": [("veh_2", "us-east"), ("veh_9", "us-west")],
                        "heartbeat_missed": [("veh_1", "us-east"), ("veh_3", "us-east")]}[kind]
            return self.page([event(f"evt_{kind}_{v}", kind, 30, vehicle=v, region=r)
                              for v, r in vehicles], request)
        if path == "/v1/incidents/search":
            self.search_bodies.append(json.loads(request.content))
            assert params["limit"] == "5"
            return {"items": [
                {"incidentId": "inc_a", "similarity": 0.9, "resolution": "Battery replaced"},
                {"incidentId": "inc_b", "similarity": 0.6, "resolution": "Firmware updated"},
            ], "nextCursor": ""}
        if path.startswith("/v1/incidents/") and path.endswith("/resolution"):
            incident_id = path.split("/")[3]
            cause = {"inc_a": "Battery aging", "inc_b": "Firmware fault"}[incident_id]
            return {"incidentId": incident_id, "rootCause": cause, "timeToResolveMinutes": 170}
        if path == "/v1/incident-patterns/resolutions":
            return {"eventType": params["event_type"],
                    "patterns": [{"resolution": "Inspect battery", "occurrences": 12}]}
        if path == "/v1/incident-statistics/resolution-time":
            return {"eventType": params["event_type"], "sampleSize": 20, "medianMinutes": 150}
        if path == "/v1/playbooks/search":
            found = {"battery_voltage": ("pb_battery_voltage", "Battery Voltage Triage", 0.9),
                     "heartbeat_missed": ("pb_connectivity_loss", "Connectivity Loss", 0.8),
                     "diagnostic_failure": ("pb_battery_voltage", "Battery Voltage Triage", 0.3)}
            playbook_id, title, score = found[params["query"]]
            return {"items": [{"playbookId": playbook_id, "title": title, "score": score,
                               "version": "1.0"}], "nextCursor": ""}
        if path.startswith("/v1/actions/"):
            return {"actionType": path.split("/")[3], "approvalMode": "required"}
        raise AssertionError(f"unexpected call {host}{path}")


def clients(services: Services) -> ServiceClients:
    return ServiceClients(transport=httpx.MockTransport(services))


@pytest.mark.anyio
async def test_bundle_gathers_every_section_and_computes_features() -> None:
    services = Services()
    bundle = await build_evidence(clients(services), INCIDENT, NOW)

    assert bundle["schema"] == SCHEMA and bundle["gaps"] == []
    assert bundle["unit"]["firmwareVersion"] == "3.4.1"
    assert bundle["fleet"]["sla"]["responseTargetMinutes"] == 30
    # Similar incidents are searched with the rule's symptoms and enriched with root causes.
    assert services.search_bodies == [{"eventType": "battery_voltage",
                                       "symptoms": INCIDENT["symptoms"], "regionCode": "us-east"}]
    assert [s["rootCause"] for s in bundle["similarIncidents"]] == ["Battery aging",
                                                                    "Firmware fault"]
    # One entry per playbook, with its best score.
    assert [(p["playbookId"], p["score"]) for p in bundle["playbooks"]] == [
        ("pb_battery_voltage", 0.9), ("pb_connectivity_loss", 0.8)]
    assert len(bundle["actions"]) == len(evidence.ACTIONS)

    features = bundle["features"]
    assert features["batteryVoltageLatest"] == 11.4
    assert features["batteryVoltageMin24h"] == 11.4
    assert features["batteryVoltageTrendVPerHour"] == pytest.approx(-0.167, abs=0.01)
    assert features["lowVoltageReadings24h"] == 10           # 11.77 V and below
    assert features["heartbeatsMissed24h"] == 1 and features["dtcCodes24h"] == ["P0562"]
    assert features["daysSinceLastBatteryService"] == pytest.approx(200, abs=0.1)
    assert features["daysSinceLastMaintenance"] == pytest.approx(30, abs=0.1)
    # veh_2 and veh_3 also had connectivity trouble in us-east; veh_9 is elsewhere.
    assert features["regionOtherVehiclesWithConnectivityIssues1h"] == 2
    assert bundle["regional"]["byRegion"]["us-west"] == {
        "connectivity_lostVehicles": 1, "heartbeat_missedVehicles": 0}
    assert features["similarIncidentTopRootCause"] == "Battery aging"

    # Routine traffic is counted but not carried; battery readings are carried as a series.
    recent = bundle["recentEvents"]
    assert recent["countsByType"]["location"] == 72
    assert [e["eventType"] for e in recent["notable"]] == ["heartbeat_missed",
                                                           "diagnostic_failure"]
    assert len(recent["batteryVoltage"]) == 25

    citations = bundle["citations"]
    for ref in ("vehicle", "unit", "fleet", "regional", "event:evt_t1", "event:evt_b00",
                "alert:al_1", "maintenance:mnt_old", "incident:inc_a",
                "playbook:pb_connectivity_loss", "feature:batteryVoltageTrendVPerHour"):
        assert ref in citations, ref
    assert not any(ref.startswith(("event:evt_h", "event:evt_l")) for ref in citations)


@pytest.mark.anyio
async def test_missing_or_refused_sources_become_gaps() -> None:
    services = Services()
    services.missing.add("/v1/telematics-units/tcu_1")
    services.refused.add("/v1/vehicles/veh_1/maintenance-records")
    bundle = await build_evidence(clients(services), INCIDENT, NOW)
    assert {(g["section"], g["reason"]) for g in bundle["gaps"]} == {
        ("unit", "not found"), ("maintenance", "HTTP 403")}
    assert bundle["unit"] is None and bundle["maintenance"] == []
    assert bundle["features"]["firmwareVersion"] is None
    assert "unit" not in bundle["citations"]


@pytest.mark.anyio
async def test_an_unavailable_source_fails_the_bundle_so_the_outbox_retries() -> None:
    services = Services()
    services.down.add("incident-search")
    with pytest.raises(DependencyUnavailable):
        await build_evidence(clients(services), INCIDENT, NOW)
    services = Services()
    services.unavailable_dependencies = ["digital-twin-context"]
    with pytest.raises(DependencyUnavailable):
        await build_evidence(clients(services), INCIDENT, NOW)


@pytest.mark.anyio
async def test_oversized_bundle_drops_oldest_notable_events(monkeypatch) -> None:
    services = Services()
    services.events = sorted(
        services.events + [event(f"evt_x{n:03d}", "harsh_braking", 300 - n, note="x" * 200)
                           for n in range(150)],
        key=lambda e: e["observedAt"], reverse=True)
    full = await build_evidence(clients(services), INCIDENT, NOW)
    assert len(full["recentEvents"]["notable"]) == evidence.MAX_NOTABLE
    monkeypatch.setattr(evidence, "MAX_BYTES", evidence.size(full) - 5_000)
    small = await build_evidence(clients(services), INCIDENT, NOW)
    kept = small["recentEvents"]["notable"]
    assert len(kept) < evidence.MAX_NOTABLE and kept[-1]["eventId"] == "evt_t3"  # newest stay
    assert evidence.size(small) <= evidence.MAX_BYTES
    assert small["gaps"][-1]["section"] == "recentEvents"
    dropped = {e["eventId"] for e in full["recentEvents"]["notable"]} - {
        e["eventId"] for e in kept}
    assert dropped and not any(f"event:{d}" in small["citations"] for d in dropped)


@pytest.mark.anyio
async def test_detected_step_exports_evidence_before_the_message(tmp_path) -> None:
    services = Services()
    writes: list[str] = []

    class Recording(FileSink):
        async def put(self, collection, documents):
            writes.append(collection)
            await super().put(collection, documents)

        async def publish(self, topic, data, **kwargs):
            writes.append("publish")
            await super().publish(topic, data, **kwargs)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/correlation/incidents/inc_1":
            return httpx.Response(200, json=INCIDENT)
        return services(request)

    exporter = Exporter(Recording(tmp_path), ServiceClients(transport=httpx.MockTransport(
        handler)), context_interval=0, clock=lambda: NOW)
    change = {"incidentId": "inc_1", "step": "detected", "stepId": 1, "at": at(10)}
    result = await exporter.export_incident_change(change)
    await exporter.export_incident_change({**change, "step": "scored", "stepId": 2})

    assert writes == ["evidence", "incidents", "publish", "incidents", "publish"]
    assert result["evidenceRef"] == "evidence/inc_1"
    lines = [json.loads(line) for line in
             (tmp_path / "topics" / "fleetops-incidents.jsonl").read_text().splitlines()]
    assert lines[0]["attributes"]["evidenceRef"] == "evidence/inc_1"
    assert lines[0]["data"]["evidenceRef"] == "evidence/inc_1"
    assert "evidenceRef" not in lines[1]["attributes"] and lines[1]["data"]["evidenceRef"] is None
    stored = json.loads((tmp_path / "collections" / "evidence" / "inc_1.json").read_text())
    assert stored["incidentId"] == "inc_1" and stored["features"]["heartbeatsMissed24h"] == 1
