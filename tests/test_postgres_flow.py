"""End-to-end flows against a real PostgreSQL.

Set FLEETOPS_TEST_DATABASE_URL to an admin connection, for example
    postgresql://postgres:<password>@localhost:5432/postgres
Each run drops and recreates fleetops_test_<service> databases on that server, applies the
migrations, and wires all 16 services together in-process. Skipped when the variable is unset.
"""

import os
import sys
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from psycopg import AsyncConnection, sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from cloud_exporter.app import build_app as build_exporter
from cloud_exporter.exporter import Exporter
from cloud_exporter.sinks import FileSink
from fleetops_runtime import Database, MeshTransport, ServiceClients, build_app
from fleetops_runtime.outbox import dispatch_once

from conftest import all_services

ADMIN_URL = os.environ.get("FLEETOPS_TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(not ADMIN_URL, reason="FLEETOPS_TEST_DATABASE_URL is not set"),
]


@dataclass
class Mesh:
    http: httpx.AsyncClient
    databases: dict[str, Database]
    clients: ServiceClients
    exports: Path   # the cloud exporter's file sink

    async def call(self, method: str, slug: str, path: str, **kwargs) -> httpx.Response:
        return await self.http.request(method, f"http://{slug}:8080{path}", **kwargs)

    async def ok(self, method: str, slug: str, path: str, **kwargs) -> dict:
        response = await self.call(method, slug, path, **kwargs)
        assert response.status_code == 200, (method, slug, path, response.text)
        return response.json()

    async def error(self, status: int, method: str, slug: str, path: str, **kwargs) -> str:
        response = await self.call(method, slug, path, **kwargs)
        assert response.status_code == status, (method, slug, path, response.text)
        detail = response.json()["detail"]
        return detail["code"] if isinstance(detail, dict) else "VALIDATION"

    async def deliver(self, slug: str) -> int:
        return await dispatch_once(self.databases[slug], self.clients)


@pytest.fixture(scope="module")
async def mesh(anyio_backend, tmp_path_factory):
    transport = MeshTransport()
    clients = ServiceClients(transport=transport)
    exports = tmp_path_factory.mktemp("cloud-export")
    transport.apps["cloud-exporter"] = build_exporter(
        Exporter(FileSink(exports), clients, context_interval=0), run_background=False)
    databases: dict[str, Database] = {}
    async with await AsyncConnection.connect(ADMIN_URL, autocommit=True) as admin:
        for slug, service in all_services().items():
            database = None
            if service.migrations_dir is not None:
                name = "fleetops_test_" + slug.replace("-", "_")
                await admin.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
                )
                await admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
                url = make_conninfo(**{**conninfo_to_dict(ADMIN_URL), "dbname": name})
                database = Database(url, service.migrations_dir, max_size=3)
                await database.open()
                databases[slug] = database
            transport.apps[slug] = build_app(
                service.contract, service.handlers, database=database, services=clients,
                run_background=False,
            )
    async with httpx.AsyncClient(transport=transport) as http:
        yield Mesh(http, databases, clients, exports)
    for database in databases.values():
        await database.close()


def unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def recently(minutes: int = 0) -> str:
    return (datetime.now(UTC) - timedelta(minutes=30 - minutes)).isoformat()


async def test_migrations_are_recorded_and_idempotent(mesh: Mesh) -> None:
    for database in mesh.databases.values():
        assert await database.migrate() == []
    ready = await mesh.ok("GET", "fleet-master", "/health/ready")
    assert ready["status"] == "ready"


async def master_data(mesh: Mesh) -> dict[str, str]:
    provider = await mesh.ok("POST", "service-provider-master", "/v1/service-providers", json={
        "providerName": "East Battery Service", "regions": ["us-east"],
        "capabilities": ["battery", "diagnostics"], "dailyCapacity": 10,
    })
    fleet = await mesh.ok("POST", "fleet-master", "/v1/fleets", json={
        "customerName": "Northstar Logistics", "industryCode": "logistics",
        "contractTier": "enterprise", "slaLevel": "mission_critical", "priorityLevel": "high",
        "preferredServiceProviderId": provider["providerId"], "operatingRegions": ["us-east"],
    })
    unit = await mesh.ok("POST", "telematics-unit-master", "/v1/telematics-units", json={
        "serialNumber": unique("SN"), "hardwareModel": "NX-5G", "firmwareVersion": "3.4.1",
        "lifecycleStatus": "active", "capabilities": ["diagnostics", "location"],
    })
    vehicle = await mesh.ok("POST", "vehicle-master", "/v1/vehicles", json={
        "syntheticVin": uuid.uuid4().hex[:17].upper(), "make": "Nova", "model": "Transit-E",
        "modelYear": 2026, "powertrainType": "battery_electric", "regionCode": "us-east",
        "fleetId": fleet["fleetId"], "telematicsUnitId": unit["unitId"],
    })
    return {
        "provider": provider["providerId"], "fleet": fleet["fleetId"],
        "unit": unit["unitId"], "vehicle": vehicle["vehicleId"],
    }


async def test_master_data_crud_and_rules(mesh: Mesh) -> None:
    ids = await master_data(mesh)
    vehicle_path = f"/v1/vehicles/{ids['vehicle']}"

    vehicle = await mesh.ok("GET", "vehicle-master", vehicle_path)
    assert vehicle["fleetId"] == ids["fleet"] and vehicle["sourceVersion"] == 1

    updated = await mesh.ok("PATCH", "vehicle-master", vehicle_path, json={"priorityLevel": "high"})
    assert updated["priorityLevel"] == "high" and updated["sourceVersion"] == 2
    assert await mesh.error(422, "PATCH", "vehicle-master", vehicle_path, json={"make": None})
    assert await mesh.error(422, "PATCH", "vehicle-master", vehicle_path, json={}) == "EMPTY_UPDATE"

    listed = await mesh.ok("GET", "vehicle-master", "/v1/vehicles",
                           params={"fleet_id": ids["fleet"]})
    assert [item["vehicleId"] for item in listed["items"]] == [ids["vehicle"]]

    # References to other services are checked.
    code = await mesh.error(422, "PUT", "vehicle-master", f"{vehicle_path}/fleet-assignment",
                            json={"fleetId": "flt_missing"})
    assert code == "UNKNOWN_FLEET"
    other = await mesh.ok("POST", "vehicle-master", "/v1/vehicles", json={
        "syntheticVin": uuid.uuid4().hex[:17].upper(), "make": "Nova", "model": "Van",
        "modelYear": 2025, "powertrainType": "diesel", "regionCode": "us-east",
    })
    code = await mesh.error(409, "PUT", "vehicle-master",
                            f"/v1/vehicles/{other['vehicleId']}/telematics-unit-assignment",
                            json={"telematicsUnitId": ids["unit"]})
    assert code == "TELEMATICS_UNIT_ASSIGNED"

    # Lifecycle rules: retiring is terminal and frees the telematics unit.
    retired = await mesh.ok("PUT", "vehicle-master", f"/v1/vehicles/{other['vehicleId']}/lifecycle-status",
                            json={"status": "retired"})
    assert retired["serviceStatus"] == "retired"
    code = await mesh.error(409, "PUT", "vehicle-master",
                            f"/v1/vehicles/{other['vehicleId']}/lifecycle-status",
                            json={"status": "active"})
    assert code == "INVALID_TRANSITION"

    fleet = await mesh.ok("GET", "fleet-master", f"/v1/fleets/{ids['fleet']}")
    assert fleet["operatingRegions"] == ["us-east"]
    sla = await mesh.ok("GET", "fleet-master", f"/v1/fleets/{ids['fleet']}/sla")
    assert sla["responseTargetMinutes"] == 30
    contacts = await mesh.ok("PUT", "fleet-master", f"/v1/fleets/{ids['fleet']}/escalation-contacts",
                             json={"contacts": [{"name": "Dana", "role": "fleet_manager",
                                                 "email": "dana@example.invalid"}]})
    assert contacts["contacts"][0]["escalationRank"] == 1
    assert await mesh.error(422, "PUT", "fleet-master",
                            f"/v1/fleets/{ids['fleet']}/escalation-contacts",
                            json={"contacts": [{"name": "No Method", "role": "x"}]})

    providers = await mesh.ok("GET", "service-provider-master", "/v1/service-providers",
                              params={"region": "us-east", "capability": "battery"})
    assert ids["provider"] in [item["providerId"] for item in providers["items"]]

    unit = await mesh.ok("PUT", "telematics-unit-master",
                         f"/v1/telematics-units/{ids['unit']}/remote-command-eligibility",
                         json={"eligibility": "approval_required"})
    assert unit["remoteCommandEligibility"] == "approval_required"

    record = await mesh.ok("POST", "maintenance-history", "/v1/maintenance-records", json={
        "vehicleId": ids["vehicle"], "serviceProviderId": ids["provider"],
        "eventType": "inspection", "serviceStatus": "in_progress",
        "openedAt": recently(), "summary": "Battery check",
    })
    assert record["completedAt"] is None
    code = await mesh.error(422, "POST", "maintenance-history",
                            f"/v1/maintenance-records/{record['maintenanceId']}/corrections",
                            json={"reason": "done", "changes": {"serviceStatus": "completed"}})
    assert code == "COMPLETION_TIME_REQUIRED"
    corrected = await mesh.ok("POST", "maintenance-history",
                              f"/v1/maintenance-records/{record['maintenanceId']}/corrections",
                              json={"reason": "done", "changes": {
                                  "serviceStatus": "completed", "completedAt": recently(5),
                                  "resolution": "Battery replaced"}})
    assert corrected["sourceVersion"] == 2 and corrected["serviceStatus"] == "completed"
    history = await mesh.ok("GET", "maintenance-history",
                            f"/v1/vehicles/{ids['vehicle']}/maintenance-records")
    assert [item["maintenanceId"] for item in history["items"]] == [record["maintenanceId"]]


async def test_pagination_walks_every_page(mesh: Mesh) -> None:
    fleet = await mesh.ok("POST", "fleet-master", "/v1/fleets", json={
        "customerName": "Paging Fleet", "industryCode": "logistics",
        "contractTier": "basic", "slaLevel": "standard",
    })
    created = set()
    for _ in range(5):
        vehicle = await mesh.ok("POST", "vehicle-master", "/v1/vehicles", json={
            "syntheticVin": uuid.uuid4().hex[:17].upper(), "make": "Nova", "model": "Van",
            "modelYear": 2024, "powertrainType": "hybrid", "regionCode": "us-west",
            "fleetId": fleet["fleetId"],
        })
        created.add(vehicle["vehicleId"])
    seen, cursor = [], None
    while True:
        params = {"fleet_id": fleet["fleetId"], "limit": 2, **({"cursor": cursor} if cursor else {})}
        page = await mesh.ok("GET", "vehicle-master", "/v1/vehicles", params=params)
        seen += [item["vehicleId"] for item in page["items"]]
        cursor = page["nextCursor"]
        if not cursor:
            break
    assert sorted(seen) == sorted(created) and len(seen) == 5


async def test_events_alerts_twin_and_risk(mesh: Mesh) -> None:
    ids = await master_data(mesh)
    vehicle = ids["vehicle"]
    low = {"eventId": unique("evt"), "vehicleId": vehicle, "eventType": "battery_voltage",
           "observedAt": recently(1), "payload": {"voltage": 11.4}}

    accepted = await mesh.ok("POST", "telematics-event", "/v1/events", json=low)
    assert accepted["status"] == "accepted"
    again = await mesh.ok("POST", "telematics-event", "/v1/events", json=low)
    assert again["status"] == "duplicate"
    changed = {**low, "payload": {"voltage": 10.0}}
    assert await mesh.error(409, "POST", "telematics-event", "/v1/events", json=changed) == (
        "EVENT_ID_CONFLICT"
    )
    assert await mesh.error(422, "POST", "telematics-event", "/v1/events",
                            json={**low, "eventId": unique("evt"), "payload": {}}) == "INVALID_PAYLOAD"
    assert await mesh.error(422, "POST", "telematics-event", "/v1/events",
                            json={**low, "eventId": unique("evt"), "vehicleId": "veh_missing"}) == (
        "UNKNOWN_VEHICLE"
    )

    event = await mesh.ok("GET", "telematics-event", f"/v1/events/{low['eventId']}")
    assert event["severity"] == "warning" and event["regionCode"] == "us-east"
    alerts = await mesh.ok("GET", "telematics-event", f"/v1/vehicles/{vehicle}/active-alerts")
    assert [alert["alertType"] for alert in alerts["alerts"]] == ["battery_voltage"]

    # The twin only changes when the outbox delivers the event.
    assert await mesh.error(404, "GET", "digital-twin-context", f"/v1/digital-twins/vehicles/{vehicle}")
    assert await mesh.deliver("telematics-event") >= 1
    state = await mesh.ok("GET", "digital-twin-context", f"/v1/digital-twins/vehicles/{vehicle}")
    assert state["healthState"] == "warning" and state["fleetId"] == ids["fleet"]
    assert state["batteryVoltage"] == 11.4

    fleet_state = await mesh.ok("GET", "digital-twin-context", f"/v1/digital-twins/fleets/{ids['fleet']}")
    assert fleet_state["warningVehicleCount"] == 1
    listed = await mesh.ok("GET", "digital-twin-context", "/v1/digital-twins/vehicles",
                           params={"fleet_id": ids["fleet"], "health_state": "warning"})
    assert [item["vehicleId"] for item in listed["items"]] == [vehicle]
    assert listed["items"][0]["batteryVoltage"] == 11.4
    healthy = await mesh.ok("GET", "digital-twin-context", "/v1/digital-twins/vehicles",
                            params={"fleet_id": ids["fleet"], "health_state": "healthy"})
    assert healthy["items"] == []
    assert await mesh.error(422, "GET", "digital-twin-context", "/v1/digital-twins/vehicles",
                            params={"health_state": "unknown"}) == "INVALID_HEALTH_STATE"
    impact = await mesh.ok("GET", "digital-twin-context",
                           f"/v1/digital-twins/events/{low['eventId']}/downstream-impact")
    assert impact["affectedFleetIds"] == [ids["fleet"]] and impact["riskLevel"] == "medium"
    graph = await mesh.ok("GET", "digital-twin-context",
                          f"/v1/digital-twins/entities/{vehicle}/dependency-graph")
    assert {node["entityId"] for node in graph["nodes"]} == {
        vehicle, ids["fleet"], ids["unit"], ids["provider"]
    }

    risk = await mesh.ok("GET", "risk-scoring", f"/v1/risk/events/{low['eventId']}/composite-priority")
    assert set(risk["componentScores"]) == {"event", "safety", "sla"}
    assert risk["confidence"] == 1.0

    context = await mesh.ok("GET", "vehicle-context-facade", f"/v1/vehicle-context/{vehicle}")
    assert context["operationalState"]["healthState"] == "warning"
    assert context["unavailableDependencies"] == []

    # A normal reading clears the alert and, once delivered, the twin's battery issue.
    normal = {"vehicleId": vehicle, "eventType": "battery_voltage", "observedAt": recently(2),
              "payload": {"voltage": 12.6}}
    await mesh.ok("POST", "telematics-event", "/v1/events", json=normal)
    alerts = await mesh.ok("GET", "telematics-event", f"/v1/vehicles/{vehicle}/active-alerts")
    assert alerts["alerts"] == []
    await mesh.deliver("telematics-event")
    state = await mesh.ok("GET", "digital-twin-context", f"/v1/digital-twins/vehicles/{vehicle}")
    assert state["healthState"] == "healthy"

    # A late, older event is recorded but does not roll the state back.
    late = {"eventId": unique("evt"), "vehicleId": vehicle, "eventType": "battery_voltage",
            "observedAt": recently(0), "payload": {"voltage": 10.5}}
    await mesh.ok("POST", "telematics-event", "/v1/events", json=late)
    alerts = await mesh.ok("GET", "telematics-event", f"/v1/vehicles/{vehicle}/active-alerts")
    assert alerts["alerts"] == []
    await mesh.deliver("telematics-event")
    state = await mesh.ok("GET", "digital-twin-context", f"/v1/digital-twins/vehicles/{vehicle}")
    assert state["healthState"] == "healthy"

    window = {"from": recently(-1), "to": datetime.now(UTC).isoformat()}
    events = await mesh.ok("GET", "telematics-event", f"/v1/vehicles/{vehicle}/events", params=window)
    assert len(events["items"]) == 3
    by_region = await mesh.ok("GET", "telematics-event", "/v1/regions/us-east/events", params=window)
    assert {item["eventId"] for item in events["items"]} <= {
        item["eventId"] for item in by_region["items"]
    }


async def test_case_resolution_feeds_incident_search(mesh: Mesh) -> None:
    ids = await master_data(mesh)
    recommendation = unique("rec")
    case = await mesh.ok("POST", "case-management", "/v1/cases", json={
        "vehicleId": ids["vehicle"], "recommendationId": recommendation,
        "summary": "Inspect low battery voltage", "eventType": "battery_voltage",
        "symptoms": ["low_voltage", "missed_heartbeat"],
    })
    assert case["workflowState"] == "triage"
    code = await mesh.error(409, "POST", "case-management", "/v1/cases", json={
        "vehicleId": ids["vehicle"], "recommendationId": recommendation, "summary": "again",
    })
    assert code == "CASE_EXISTS_FOR_RECOMMENDATION"

    path = f"/v1/cases/{case['caseId']}"
    assert await mesh.error(409, "PUT", "case-management", f"{path}/status",
                            json={"status": "in_progress"}) == "CASE_NOT_ASSIGNED"
    assigned = await mesh.ok("PUT", "case-management", f"{path}/assignment",
                             json={"teamId": "team_fleet_ops"})
    assert assigned["workflowState"] == "assigned"
    await mesh.ok("PUT", "case-management", f"{path}/status", json={"status": "in_progress"})
    assert await mesh.error(422, "PUT", "case-management", f"{path}/status",
                            json={"status": "resolved"}) == "RESOLUTION_REQUIRED"
    resolved = await mesh.ok("PUT", "case-management", f"{path}/status", json={
        "status": "resolved", "resolution": "Battery replaced", "rootCause": "Battery aging",
    })
    assert resolved["status"] == "resolved"
    attachment = await mesh.ok("POST", "case-management", f"{path}/agent-summaries",
                               json={"summary": "Evidence summary", "traceId": "trace_1"})
    assert attachment["type"] == "agent_summary"

    assert await mesh.deliver("case-management") == 1
    found = await mesh.ok("POST", "incident-search", "/v1/incidents/search", json={
        "eventType": "battery_voltage", "symptoms": ["low_voltage"], "regionCode": "us-east",
    })
    top = found["items"][0]
    assert top["incidentId"].startswith(f"inc_{case['caseId']}")
    assert top["similarity"] == pytest.approx(0.5 + 0.3 * 0.5 + 0.2, abs=0.001)
    stats = await mesh.ok("GET", "incident-search", "/v1/incident-statistics/resolution-time",
                          params={"event_type": "battery_voltage"})
    assert stats["sampleSize"] >= 1
    patterns = await mesh.ok("GET", "incident-search", "/v1/incident-patterns/resolutions",
                             params={"event_type": "battery_voltage"})
    assert patterns["patterns"][0]["resolution"] == "Battery replaced"


async def test_idempotency_key_replays_the_first_response(mesh: Mesh) -> None:
    ids = await master_data(mesh)
    body = {"vehicleId": ids["vehicle"], "summary": "Retry-safe case"}
    key = {"Idempotency-Key": unique("key")}
    first = await mesh.ok("POST", "case-management", "/v1/cases", json=body, headers=key)
    second = await mesh.ok("POST", "case-management", "/v1/cases", json=body, headers=key)
    assert first["caseId"] == second["caseId"]
    code = await mesh.error(422, "POST", "case-management", "/v1/cases",
                            json={**body, "summary": "different"}, headers=key)
    assert code == "IDEMPOTENCY_KEY_REUSED"


async def test_approval_gates_fleet_manager_notification(mesh: Mesh) -> None:
    ids = await master_data(mesh)
    event = await mesh.ok("POST", "telematics-event", "/v1/events", json={
        "vehicleId": ids["vehicle"], "eventType": "battery_voltage", "observedAt": recently(),
        "payload": {"voltage": 11.2},
    })
    draft = await mesh.ok("POST", "notification", "/v1/notifications/fleet-drafts",
                          json={"fleetId": ids["fleet"], "eventId": event["eventId"]})
    assert draft["status"] == "draft" and "Northstar Logistics" in draft["message"]

    approval = await mesh.ok("POST", "approval", "/v1/approvals", json={
        "actionId": unique("act"), "actionType": "fleet_notification", "riskLevel": "high",
        "evidenceTraceId": "trace_1", "requestedReviewerRole": "operations_manager",
    })
    assert approval["status"] == "pending" and approval["decidedAt"] is None
    send = {"fleetId": ids["fleet"], "message": draft["message"],
            "approvalId": approval["approvalId"]}
    assert await mesh.error(403, "POST", "notification", "/v1/notifications/fleet-manager",
                            json=send) == "APPROVAL_NOT_GRANTED"

    pending = await mesh.ok("GET", "approval", "/v1/approvals",
                            params={"reviewer_id": "reviewer_ops_001"})
    assert approval["approvalId"] in [item["approvalId"] for item in pending["items"]]

    decision_path = f"/v1/approvals/{approval['approvalId']}/decisions"
    decision = {"decision": "approved", "comments": "ok"}
    assert await mesh.error(403, "POST", "approval", decision_path, json=decision,
                            headers={"X-Reviewer-Id": "reviewer_safety_001"}) == "WRONG_REVIEWER_ROLE"
    decided = await mesh.ok("POST", "approval", decision_path, json=decision,
                            headers={"X-Reviewer-Id": "reviewer_ops_001"})
    assert decided["status"] == "approved" and decided["reviewerId"] == "reviewer_ops_001"
    assert await mesh.error(409, "POST", "approval", decision_path, json=decision,
                            headers={"X-Reviewer-Id": "reviewer_ops_001"}) == "APPROVAL_ALREADY_DECIDED"

    sent = await mesh.ok("POST", "notification", "/v1/notifications/fleet-manager", json=send)
    assert sent["status"] == "delivered"
    assert await mesh.error(409, "POST", "notification", "/v1/notifications/fleet-manager",
                            json=send) == "APPROVAL_ALREADY_USED"
    status = await mesh.ok("GET", "notification", f"/v1/notifications/{sent['notificationId']}")
    assert status["attemptCount"] == 1


async def test_policy_lookups(mesh: Mesh) -> None:
    found = await mesh.ok("GET", "policy-playbook", "/v1/playbooks/search",
                          params={"query": "battery voltage"})
    assert found["items"][0]["playbookId"] == "pb_battery_voltage"
    eligibility = await mesh.ok("GET", "policy-playbook", "/v1/action-eligibility",
                                params={"action_type": "create_service_case", "risk_level": "low"})
    assert eligibility["eligible"] is True
    eligibility = await mesh.ok("GET", "policy-playbook", "/v1/action-eligibility",
                                params={"action_type": "fleet_notification", "risk_level": "low"})
    assert eligibility["eligible"] is False and eligibility["approvalRequired"] is True
    blocked = await mesh.ok("GET", "policy-playbook", "/v1/action-eligibility",
                            params={"action_type": "customer_notification", "risk_level": "low"})
    assert blocked["eligible"] is False and blocked["approvalRequired"] is False
    rules = await mesh.ok("GET", "policy-playbook", "/v1/escalation-rules",
                          params={"event_type": "collision_detected", "severity": "critical"})
    assert [rule["ruleId"] for rule in rules["rules"]] == [
        "rule_collision_critical", "rule_any_critical"
    ]
    policy = await mesh.ok("GET", "policy-playbook", "/v1/policies/policy_remote_action")
    assert policy["status"] == "active"


async def test_seed_loader_loads_csvs_and_reruns_cleanly(mesh: Mesh, tmp_path) -> None:
    from fleetops_seed import Loader, build_catalog, mesh_urls
    from fleetops_seed.csvio import read_catalog, write_catalog

    # Seed IDs (veh_0001, flt_golden, ...) never collide with the random IDs other tests use.
    write_catalog(build_catalog(providers=4, fleets=3, vehicles=25, spare_units=2,
                                incidents=10), tmp_path)
    catalog = read_catalog(tmp_path)

    first = await Loader(mesh.http, mesh_urls).load(catalog)
    assert first.failures == []
    counts = catalog.counts()
    for kind, expected in counts.items():
        assert first.created[kind] == expected, kind
    assert first.created["contacts"] == counts["fleets"]

    second = await Loader(mesh.http, mesh_urls).load(catalog)
    assert second.failures == []
    for kind, expected in counts.items():
        assert second.existing[kind] == expected and second.created[kind] == 0, kind

    fleet = catalog.fleets[0]
    members = await mesh.ok("GET", "vehicle-master", "/v1/vehicles",
                            params={"fleet_id": fleet["fleetId"], "limit": 200})
    assert len(members["items"]) == fleet["declaredFleetSize"]


async def test_simulator_drives_events_alerts_and_twin(mesh: Mesh, tmp_path) -> None:
    from fleetops_seed import Loader, build_catalog, mesh_urls
    from fleetops_sim import Injection, RunConfig, Simulator

    write_seed = build_catalog(providers=4, fleets=3, vehicles=25, spare_units=2, incidents=10)
    report = await Loader(mesh.http, mesh_urls).load(write_seed)
    assert report.failures == []

    start = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(minutes=30)
    config = RunConfig(start=start, minutes=30, max_vehicles=8, seed=unique("sim"),
                       injections=[Injection("battery_connectivity", "veh_golden_001", 5)])
    stats = await Simulator(mesh.http, mesh_urls, config).run()
    assert stats.failures == [], stats.failures
    assert stats.outcome["accepted"] == sum(stats.sent.values()) > 0

    alerts = await mesh.ok("GET", "telematics-event", "/v1/vehicles/veh_golden_001/active-alerts")
    assert {"battery_voltage", "diagnostic_failure"} <= {a["alertType"] for a in alerts["alerts"]}

    while await mesh.deliver("telematics-event"):
        pass
    state = await mesh.ok("GET", "digital-twin-context",
                          "/v1/digital-twins/vehicles/veh_golden_001")
    assert state["healthState"] == "critical"
    assert {issue["issue"] for issue in state["activeIssues"]} >= {"battery", "diagnostic"}
    fleet = await mesh.ok("GET", "digital-twin-context", "/v1/digital-twins/fleets/flt_golden")
    assert fleet["criticalVehicleCount"] == 1
    pages, cursor = [], None
    while True:
        page = await mesh.ok("GET", "digital-twin-context", "/v1/digital-twins/vehicles",
                             params={"fleet_id": "flt_golden", "limit": 2, "cursor": cursor}
                             if cursor else {"fleet_id": "flt_golden", "limit": 2})
        pages.append([item["vehicleId"] for item in page["items"]])
        if not (cursor := page["nextCursor"]):
            break
    walked = [vehicle for page in pages for vehicle in page]
    assert walked == sorted(set(walked)) and len(walked) == fleet["vehicleCount"]
    assert "veh_golden_001" in walked

    # The scripted fault is the battery-connectivity pattern, so it becomes an incident.
    incidents = await mesh.ok("GET", "signal-correlation", "/v1/correlation/incidents",
                              params={"vehicle_id": "veh_golden_001"})
    assert [item["ruleId"] for item in incidents["items"]] == ["battery-connectivity-v1"]


async def test_audit_is_append_only(mesh: Mesh) -> None:
    trace = unique("trace")
    started = {"eventId": unique("audit"), "traceId": trace, "agentName": "triage",
               "eventType": "run_started", "occurredAt": recently(), "payload": {}}
    assert (await mesh.ok("POST", "audit-observability", "/v1/audit/agent-traces",
                          json=started))["status"] == "recorded"
    assert (await mesh.ok("POST", "audit-observability", "/v1/audit/agent-traces",
                          json=started))["status"] == "duplicate"
    assert await mesh.error(409, "POST", "audit-observability", "/v1/audit/agent-traces",
                            json={**started, "eventType": "run_failed"}) == "AUDIT_EVENT_CONFLICT"
    await mesh.ok("POST", "audit-observability", "/v1/audit/tool-calls", json={
        "eventId": unique("audit"), "traceId": trace, "toolName": "get_vehicle",
        "status": "succeeded", "occurredAt": recently(1), "payload": {"latencyMs": 12},
    })
    partial = await mesh.ok("GET", "audit-observability", f"/v1/traces/{trace}")
    assert len(partial["events"]) == 2 and partial["complete"] is False
    await mesh.ok("POST", "audit-observability", "/v1/audit/agent-traces",
                  json={**started, "eventId": unique("audit"), "eventType": "run_completed",
                        "occurredAt": recently(2)})
    assert (await mesh.ok("GET", "audit-observability", f"/v1/traces/{trace}"))["complete"] is True

    with pytest.raises(Exception, match="append-only"):
        async with mesh.databases["audit-observability"].transaction() as conn:
            await conn.execute("DELETE FROM audit.audit_events WHERE trace_id = %s", (trace,))


CORRELATION = sys.modules["signal_correlation_handlers"]


async def drain(mesh: Mesh, *slugs: str) -> None:
    while sum([await mesh.deliver(slug) for slug in slugs]):
        pass


async def respond(mesh: Mesh) -> None:
    """Run the correlation worker as if its poll interval had passed."""
    database = mesh.databases["signal-correlation"]
    async with database.transaction() as conn:
        await conn.execute("UPDATE correlation.incidents SET next_attempt_at = now() "
                           "WHERE status IN ('detected', 'awaiting_approval')")
    while await CORRELATION.respond_to_incidents(database, mesh.clients):
        pass


async def send_pattern(mesh: Mesh, vehicle: str, start: int) -> list[str]:
    """Low battery, missed heartbeat, diagnostic failure, sent newest first."""
    events = [
        {"eventId": unique("evt"), "vehicleId": vehicle, "eventType": "battery_voltage",
         "observedAt": recently(start), "payload": {"voltage": 11.4}},
        {"eventId": unique("evt"), "vehicleId": vehicle, "eventType": "heartbeat_missed",
         "observedAt": recently(start + 3), "payload": {}},
        {"eventId": unique("evt"), "vehicleId": vehicle, "eventType": "diagnostic_failure",
         "observedAt": recently(start + 7), "payload": {"dtcCode": "P0562", "severity": "critical"}},
    ]
    for event in reversed(events):
        await mesh.ok("POST", "telematics-event", "/v1/events", json=event)
    await drain(mesh, "telematics-event")
    return [event["eventId"] for event in events]


async def test_correlation_turns_a_pattern_into_an_approved_case(mesh: Mesh) -> None:
    ids = await master_data(mesh)
    vehicle = ids["vehicle"]
    # A low reading alone is not a pattern (and this one is too early to join the next one).
    await mesh.ok("POST", "telematics-event", "/v1/events", json={
        "vehicleId": vehicle, "eventType": "battery_voltage", "observedAt": recently(-10),
        "payload": {"voltage": 11.5}})
    await drain(mesh, "telematics-event")
    listed = await mesh.ok("GET", "signal-correlation", "/v1/correlation/incidents",
                           params={"vehicle_id": vehicle})
    assert listed["items"] == []

    # Delivered newest first: the incident forms when the last missing piece arrives.
    triggers = await send_pattern(mesh, vehicle, 2)
    listed = await mesh.ok("GET", "signal-correlation", "/v1/correlation/incidents",
                           params={"vehicle_id": vehicle})
    assert len(listed["items"]) == 1
    incident = listed["items"][0]
    assert incident["status"] == "detected" and incident["triggerEventIds"] == triggers
    path = f"/v1/correlation/incidents/{incident['incidentId']}"

    # A redelivered signal is a duplicate and points at the incident it belongs to.
    replay = await mesh.ok("POST", "signal-correlation", "/v1/correlation/signals", json={
        "eventId": triggers[0], "vehicleId": vehicle, "eventType": "battery_voltage",
        "severity": "warning", "observedAt": recently(2), "payload": {"voltage": 11.4}})
    assert replay == {"eventId": triggers[0], "status": "duplicate",
                      "incidentId": incident["incidentId"]}

    # Mission-critical fleet and a critical diagnostic: above the autonomous limit for cases.
    await respond(mesh)
    incident = await mesh.ok("GET", "signal-correlation", path)
    assert incident["riskLevel"] in ("high", "critical")
    assert incident["policyDecision"] == "approval_required"
    assert incident["status"] == "awaiting_approval" and incident["caseId"] is None
    approval = await mesh.ok("GET", "approval", f"/v1/approvals/{incident['approvalId']}")
    assert approval["actionType"] == "create_service_case"
    assert approval["evidenceTraceId"] == incident["traceId"]

    await respond(mesh)  # still pending: nothing changes
    assert (await mesh.ok("GET", "signal-correlation", path))["status"] == "awaiting_approval"

    # The same pattern again while the incident is open adds evidence, not a new incident.
    await send_pattern(mesh, vehicle, 12)
    listed = await mesh.ok("GET", "signal-correlation", "/v1/correlation/incidents",
                           params={"vehicle_id": vehicle})
    assert len(listed["items"]) == 1

    await mesh.ok("POST", "approval", f"/v1/approvals/{incident['approvalId']}/decisions",
                  json={"decision": "approved", "comments": "Open the case"},
                  headers={"X-Reviewer-Id": "reviewer_ops_001"})
    await respond(mesh)
    incident = await mesh.ok("GET", "signal-correlation", path)
    assert incident["status"] == "case_opened"
    case = await mesh.ok("GET", "case-management", f"/v1/cases/{incident['caseId']}/status")
    assert case["status"] == "open" and case["auditTraceId"] == incident["traceId"]
    assert [step["step"] for step in incident["timeline"]] == [
        "detected", "scored", "policy_evaluated", "approval_requested", "recurred",
        "approved", "case_opened",
    ]
    roles = [(event["role"], event["ruleStep"]) for event in incident["events"]]
    assert roles.count(("trigger", "diagnostic_failure")) == 1
    assert roles.count(("supporting", "diagnostic_failure")) == 1

    # Every step reaches the audit trail under the incident's trace ID.
    await drain(mesh, "signal-correlation")
    trace = await mesh.ok("GET", "audit-observability", f"/v1/traces/{incident['traceId']}")
    assert [event["category"] for event in trace["events"]] == [
        "system_event", "system_event", "policy_decision", "system_event", "system_event",
        "human_decision", "action_outcome",
    ]

    # The same drain delivered every step to the cloud exporter: one message per step, in
    # order, each carrying a snapshot, and the stored document is the final state.
    lines = (mesh.exports / "topics" / "fleetops-incidents.jsonl").read_text().splitlines()
    exported = [json.loads(line) for line in lines]
    exported = [m for m in exported if m["orderingKey"] == incident["incidentId"]]
    assert [m["attributes"]["step"] for m in exported] == [
        step["step"] for step in incident["timeline"]]
    assert len({m["attributes"]["dedupeKey"] for m in exported}) == len(exported)
    assert exported[0]["data"]["incident"]["vehicleId"] == vehicle
    table = [json.loads(line) for line in
             (mesh.exports / "tables" / "incidents.jsonl").read_text().splitlines()]
    snapshots = [row for row in table if row["incidentId"] == incident["incidentId"]]
    assert [row["step"] for row in snapshots] == [step["step"] for step in incident["timeline"]]
    newest = max(snapshots, key=lambda row: row["sourceVersion"])   # as incidents_latest picks
    assert newest["status"] == "case_opened" and newest["incident"]["caseId"] == case["caseId"]

    # Detection and the recurrence each carried an evidence bundle built from the real services.
    with_evidence = [m["attributes"]["step"] for m in exported
                     if m["attributes"]["hasEvidence"] == "true"]
    assert with_evidence == ["detected", "recurred"]
    bundles = [row["bundle"] for row in map(json.loads, (
        mesh.exports / "tables" / "evidence.jsonl").read_text().splitlines())
        if row["incidentId"] == incident["incidentId"]]
    assert len(bundles) == 2
    bundle = bundles[-1]
    assert bundle["schema"] == "fleetops.evidence.v1" and bundle["vehicleId"] == vehicle
    assert bundle["vehicle"]["profile"]["vehicleId"] == vehicle
    assert bundle["fleet"]["sla"] is not None and bundle["unit"] is not None
    assert bundle["features"]["heartbeatsMissed24h"] >= 1
    assert bundle["features"]["dtcCodes24h"] == ["P0562"]
    assert {a["actionType"] for a in bundle["actions"]} >= {"create_service_case"}
    assert any(p["playbookId"] == "pb_battery_voltage" for p in bundle["playbooks"])
    assert all(f"event:{event_id}" in bundle["citations"]
               for event_id in incident["triggerEventIds"]), bundle["citations"]
    assert bundle["gaps"] == [], bundle["gaps"]

    # The exporter's event export reads the real feed (the 30 s settle waived for the test)
    # and appends every event the pattern produced.
    feed = sys.modules["telematics_event_handlers"]
    settle, feed.FEED_SETTLE = feed.FEED_SETTLE, timedelta(0)
    try:
        exported_events = await mesh.ok("POST", "cloud-exporter", "/v1/exports/events")
    finally:
        feed.FEED_SETTLE = settle
    assert exported_events["appended"] > 0
    event_rows = [json.loads(line) for line in
                  (mesh.exports / "tables" / "events.jsonl").read_text().splitlines()]
    assert set(incident["triggerEventIds"]) <= {row["eventId"] for row in event_rows}


    # Once closed, the next occurrence is a new incident.
    closed = await mesh.ok("POST", "signal-correlation", f"{path}/close",
                           json={"reason": "Battery replaced"})
    assert closed["status"] == "closed"
    await send_pattern(mesh, vehicle, 20)
    listed = await mesh.ok("GET", "signal-correlation", "/v1/correlation/incidents",
                           params={"vehicle_id": vehicle, "status": "detected"})
    assert len(listed["items"]) == 1


async def test_rejected_approval_opens_no_case(mesh: Mesh) -> None:
    ids = await master_data(mesh)
    await send_pattern(mesh, ids["vehicle"], 0)
    await respond(mesh)
    listed = await mesh.ok("GET", "signal-correlation", "/v1/correlation/incidents",
                           params={"vehicle_id": ids["vehicle"]})
    incident = listed["items"][0]
    await mesh.ok("POST", "approval", f"/v1/approvals/{incident['approvalId']}/decisions",
                  json={"decision": "rejected", "comments": "Known issue, already booked"},
                  headers={"X-Reviewer-Id": "reviewer_ops_001"})
    await respond(mesh)
    incident = await mesh.ok("GET", "signal-correlation",
                             f"/v1/correlation/incidents/{incident['incidentId']}")
    assert incident["status"] == "rejected" and incident["caseId"] is None
    assert incident["timeline"][-1]["step"] == "no_case"
