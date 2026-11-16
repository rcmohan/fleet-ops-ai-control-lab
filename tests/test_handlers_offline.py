"""Checks that need no database: handler wiring, pure domain rules, and the two stateless
services (risk scoring, vehicle context facade) running against stub upstream services."""

from datetime import UTC, datetime

import httpx
import pytest

from fleetops_runtime import MeshTransport, ServiceClients, build_app

from conftest import all_services

SERVICES = all_services()


def test_every_operation_has_a_handler_and_openapi_builds() -> None:
    for slug, service in SERVICES.items():
        assert service.handlers is not None, slug
        app = build_app(service.contract, service.handlers)
        spec = app.openapi()
        assert len(spec["paths"]) >= len({op.path for op in service.contract.operations}) - 1


def test_stateful_services_have_migrations() -> None:
    stateless = {"risk-scoring", "vehicle-context-facade"}
    for slug, service in SERVICES.items():
        assert (service.migrations_dir is None) == (slug in stateless), slug


def module(slug: str):
    return __import__("sys").modules[f"{slug.replace('-', '_')}_handlers"]


def test_battery_severity_thresholds() -> None:
    rules = module("telematics-event").EVENT_RULES
    classify = rules["battery_voltage"].severity
    assert classify({"voltage": 12.4}) == "info"
    assert classify({"voltage": 11.8}) == "info"
    assert classify({"voltage": 11.5}) == "warning"
    assert classify({"voltage": 10.9}) == "critical"
    assert rules["diagnostic_failure"].severity({"dtcCode": "P0562", "severity": "critical"}) == (
        "critical"
    )


def test_digital_twin_derives_health_from_open_issues() -> None:
    twin = module("digital-twin-context")
    state = {
        "issues": {}, "odometer_km": 100.0, "battery_voltage": None, "last_location": None,
    }

    def apply(event_type: str, severity: str, payload: dict, minute: int) -> dict:
        event = twin.ApplyEvent(
            eventId=f"evt_{minute}", vehicleId="veh_1", eventType=event_type, severity=severity,
            observedAt=datetime(2026, 8, 22, 12, minute, tzinfo=UTC), payload=payload,
        )
        values = twin.derive(state, event)
        state.update(
            issues=values["issues"].obj, odometer_km=values["odometer_km"],
            battery_voltage=values["battery_voltage"],
            last_location=values["last_location"].obj if values["last_location"] else None,
        )
        return values

    assert apply("battery_voltage", "warning", {"voltage": 11.5}, 0)["health_state"] == "warning"
    assert apply("heartbeat_missed", "warning", {}, 1)["connectivity_state"] == "degraded"
    assert set(state["issues"]) == {"battery", "connectivity"}
    # Any other event from the vehicle proves it is reachable again.
    values = apply("diagnostic_failure", "critical", {"dtcCode": "P0562"}, 2)
    assert values["health_state"] == "critical"
    assert values["connectivity_state"] == "connected"
    assert set(state["issues"]) == {"battery", "diagnostic"}
    apply("diagnostic_cleared", "info", {}, 3)
    values = apply("battery_voltage", "info", {"voltage": 12.6, "odometerKm": 150.5}, 4)
    assert values["health_state"] == "healthy"
    assert values["connectivity_state"] == "connected"
    assert state["issues"] == {}
    assert state["odometer_km"] == 150.5
    # Odometer never goes backwards.
    assert apply("location", "info", {"latitude": 1, "longitude": 2, "odometerKm": 90}, 5)[
        "odometer_km"
    ] == 150.5


def stub_mesh(real: set[str]) -> MeshTransport:
    mesh = MeshTransport()
    clients = ServiceClients(transport=mesh)
    for slug, service in SERVICES.items():
        handlers = service.handlers if slug in real else None
        mesh.apps[slug] = build_app(service.contract, handlers, services=clients)
    return mesh


@pytest.mark.anyio
async def test_composite_priority_combines_event_safety_and_sla() -> None:
    mesh = stub_mesh({"risk-scoring"})
    async with httpx.AsyncClient(transport=mesh) as http:
        response = await http.get(
            "http://risk-scoring:8080/v1/risk/events/evt_1/composite-priority"
        )
        assert response.status_code == 200, response.text
        body = response.json()
        # Stub inputs: battery warning, one other active alert, standard-priority vehicle,
        # mission-critical high-priority fleet, vehicle twin in warning state.
        assert body["componentScores"] == {"event": 50.0, "safety": 35.0, "sla": 75.0}
        assert body["priorityScore"] == pytest.approx(52.25, abs=0.1)
        assert body["urgency"] == "high"
        assert body["confidence"] == 1.0
        assert body["scoringPolicyVersion"] == "risk-v1"

        sla = await http.get("http://risk-scoring:8080/v1/risk/vehicles/veh_1/fleets/flt_other/sla")
        assert sla.status_code == 422
        assert sla.json()["detail"]["code"] == "VEHICLE_NOT_IN_FLEET"

        del mesh.apps["digital-twin-context"]
        degraded = (await http.get("http://risk-scoring:8080/v1/risk/events/evt_1/safety")).json()
        assert degraded["score"] == 30.0
        assert degraded["confidence"] < 1.0


@pytest.mark.anyio
async def test_vehicle_context_reports_unavailable_sources() -> None:
    mesh = stub_mesh({"vehicle-context-facade"})
    base = "http://vehicle-context-facade:8080/v1/vehicle-context/veh_9"
    async with httpx.AsyncClient(transport=mesh) as http:
        full = (await http.get(base)).json()
        assert full["profile"]["vehicleId"] == "veh_9"
        assert full["fleet"]["fleetId"] == "flt_demo_001"
        assert full["operationalState"]["healthState"] == "warning"
        assert full["unavailableDependencies"] == []

        partial = (await http.get(base, params={"include": "profile,fleet"})).json()
        assert partial["telematicsUnit"] is None and partial["operationalState"] is None

        bad = await http.get(base, params={"include": "everything"})
        assert bad.status_code == 422

        del mesh.apps["digital-twin-context"]
        degraded = (await http.get(base)).json()
        assert degraded["unavailableDependencies"] == ["digital-twin-context"]
        assert degraded["operationalState"] is None

        del mesh.apps["vehicle-master"]
        down = await http.get(base)
        assert down.status_code == 503
        assert down.json()["detail"]["dependency"] == "vehicle-master"
