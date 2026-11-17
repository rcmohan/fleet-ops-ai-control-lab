"""Fleet console: backend joins and a headless run of each page against fake services."""

from datetime import UTC, datetime, timedelta

import httpx

from fleet_console.backend import FleetBackend, is_stale

NOW = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)
RECENT = (NOW - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
OLD = (NOW - timedelta(hours=2)).isoformat().replace("+00:00", "Z")


def fleet(fleet_id: str, name: str) -> dict:
    return {"fleetId": fleet_id, "customerName": name, "industryCode": "logistics",
            "declaredFleetSize": 3, "contractTier": "enterprise", "slaLevel": "mission_critical",
            "priorityLevel": "high", "preferredServiceProviderId": "sp_1",
            "lifecycleStatus": "active", "operatingRegions": ["us-east"], "sourceVersion": 1}


def vehicle(vehicle_id: str, fleet_id: str) -> dict:
    return {"vehicleId": vehicle_id, "syntheticVin": "VIN" + vehicle_id[-3:], "make": "Nova",
            "model": "Transit-E", "modelYear": 2026, "powertrainType": "battery_electric",
            "regionCode": "us-east", "lifecycleStatus": "active", "serviceStatus": "in_service",
            "warrantyStatus": "active", "priorityLevel": "standard", "fleetId": fleet_id,
            "telematicsUnitId": "tcu_" + vehicle_id[-3:], "sourceVersion": 1}


def state(vehicle_id: str, fleet_id: str, health: str, observed: str) -> dict:
    return {"vehicleId": vehicle_id, "fleetId": fleet_id, "healthState": health,
            "connectivityState": "connected", "odometerKm": 1234.5, "batteryVoltage": 12.4,
            "lastLocation": {"latitude": 40.7, "longitude": -74.0, "speedKph": 0},
            "activeIssues": [], "observedAt": observed, "sourceVersion": 3}


FLEETS = [fleet("flt_a", "Alpha Logistics"), fleet("flt_b", "Beta Transit")]
VEHICLES = [vehicle("veh_001", "flt_a"), vehicle("veh_002", "flt_a"), vehicle("veh_003", "flt_b"),
            vehicle("veh_004", "flt_b")]
STATES = [state("veh_001", "flt_a", "critical", RECENT), state("veh_002", "flt_a", "healthy", RECENT),
          state("veh_003", "flt_b", "warning", OLD)]  # veh_004 has never reported
INCIDENT = {"incidentId": "inc_1", "ruleId": "battery-connectivity-v1", "vehicleId": "veh_001",
            "status": "case_opened", "riskLevel": "high", "caseId": "case_1",
            "detectedAt": RECENT}


def paged(items: list, request: httpx.Request) -> dict:
    """Two items per page, so callers have to follow the cursor."""
    start = int(request.url.params.get("cursor") or 0)
    rest = items[start:]
    return {"items": rest[:2], "nextCursor": str(start + 2) if len(rest) > 2 else ""}


def services(request: httpx.Request) -> httpx.Response:
    slug, path, params = request.url.host, request.url.path, request.url.params
    if slug == "fleet-master" and path == "/v1/fleets":
        return httpx.Response(200, json=paged(FLEETS, request))
    if slug == "vehicle-master" and path == "/v1/vehicles":
        wanted = [v for v in VEHICLES if params.get("fleet_id") in (None, v["fleetId"])]
        return httpx.Response(200, json=paged(wanted, request))
    if slug == "digital-twin-context" and path == "/v1/digital-twins/vehicles":
        wanted = [s for s in STATES if params.get("fleet_id") in (None, s["fleetId"])]
        return httpx.Response(200, json=paged(wanted, request))
    if slug == "signal-correlation" and path == "/v1/correlation/incidents":
        status, vehicle_id = params.get("status"), params.get("vehicle_id")
        hit = status in (None, INCIDENT["status"]) and vehicle_id in (None, INCIDENT["vehicleId"])
        return httpx.Response(200, json={"items": [INCIDENT] if hit else [], "nextCursor": ""})
    single = {
        ("fleet-master", "/v1/fleets/flt_a"): FLEETS[0],
        ("fleet-master", "/v1/fleets/flt_a/contract"): {"fleetId": "flt_a",
                                                         "contractTier": "enterprise",
                                                         "effectiveDate": "2026-01-01"},
        ("fleet-master", "/v1/fleets/flt_a/sla"): {"fleetId": "flt_a",
                                                    "slaLevel": "mission_critical",
                                                    "responseTargetMinutes": 30},
        ("service-provider-master", "/v1/service-providers/sp_1"): {
            "providerId": "sp_1", "providerName": "East Battery", "lifecycleStatus": "active",
            "averageResponseMinutes": 45, "dailyCapacity": 10, "regions": ["us-east"],
            "capabilities": ["battery"], "sourceVersion": 1},
        ("vehicle-master", "/v1/vehicles/veh_001"): VEHICLES[0],
        ("digital-twin-context", "/v1/digital-twins/vehicles/veh_001"): STATES[0],
        ("telematics-unit-master", "/v1/telematics-units/tcu_001"): {
            "unitId": "tcu_001", "serialNumber": "SN1", "hardwareModel": "NX-5G",
            "firmwareVersion": "3.4.1", "activationDate": "2026-01-01", "networkCarrier": "lte",
            "lifecycleStatus": "active", "remoteCommandEligibility": True,
            "capabilities": ["diagnostics"]},
        ("telematics-event", "/v1/vehicles/veh_001/active-alerts"): {"vehicleId": "veh_001",
                                                                    "alerts": []},
        ("telematics-event", "/v1/vehicles/veh_001/events"): {"items": [], "nextCursor": ""},
        ("maintenance-history", "/v1/vehicles/veh_001/maintenance-records"): {
            "items": [], "nextCursor": ""},
        ("case-management", "/v1/cases/case_1/status"): {
            "caseId": "case_1", "status": "open", "assignedTeamId": None,
            "workflowState": "triage", "auditTraceId": "trace_1"},
    }
    if (slug, path) in single:
        return httpx.Response(200, json=single[(slug, path)])
    return httpx.Response(404, json={"detail": {"code": "NOT_FOUND", "message": path}})


def make_backend() -> FleetBackend:
    return FleetBackend(url_for=lambda slug: f"http://{slug}",
                        transport=httpx.MockTransport(services),
                        ops_console="http://127.0.0.1:8501")


def test_fleet_rows_join_master_data_live_state_and_incidents() -> None:
    rows = {row["fleetId"]: row for row in make_backend().fleet_rows(NOW)}
    assert set(rows) == {"flt_a", "flt_b"}  # followed the cursor past the first page
    a, b = rows["flt_a"], rows["flt_b"]
    assert (a["vehicleCount"], a["healthy"], a["critical"], a["stale"], a["openIncidents"]) == (
        2, 1, 1, 0, 1)
    # An old report and no report at all both count as stale, not as their last health.
    assert (b["vehicleCount"], b["warning"], b["stale"], b["openIncidents"]) == (2, 0, 2, 0)


def test_vehicle_rows_and_staleness() -> None:
    rows = {row["vehicleId"]: row for row in make_backend().vehicle_rows("flt_b", NOW)}
    assert set(rows) == {"veh_003", "veh_004"}
    assert rows["veh_003"]["state"]["healthState"] == "warning" and rows["veh_003"]["stale"]
    assert rows["veh_004"]["state"] is None and rows["veh_004"]["stale"]
    assert not is_stale(STATES[0], NOW)
    assert make_backend().incident_link("inc_1") == "http://127.0.0.1:8501/?incident=inc_1"


def run_page(page: str, **session):
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file("../fleet_console/app.py", default_timeout=30)
    app.session_state["fleet_backend"] = make_backend()
    for key, value in session.items():
        app.session_state[key] = value
    app.run()
    if page != "Fleets":
        app.sidebar.radio[0].set_value(page).run()
    assert not app.exception, app.exception
    return app


def test_fleets_page_shows_fleets_and_a_selected_fleet() -> None:
    app = run_page("Fleets", fleet_id="flt_a")
    text = " ".join(element.value for element in app.markdown)
    assert "Alpha Logistics" in text and "East Battery" in text and "30 min" in text
    assert not app.error


def test_vehicles_page_shows_vehicle_detail_and_incident_link() -> None:
    app = run_page("Vehicles", vehicle_id="veh_001")
    text = " ".join(element.value for element in app.markdown)
    assert "veh_001" in text and "NX-5G" in text
    assert "http://127.0.0.1:8501/?incident=inc_1" in text and "case_1" in text
    assert not app.error


def test_map_page_renders() -> None:
    app = run_page("Map")
    assert not app.error


def test_pages_report_unreachable_services() -> None:
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file("../fleet_console/app.py", default_timeout=30)
    app.session_state["fleet_backend"] = FleetBackend(url_for=lambda slug: "http://127.0.0.1:9",
                                                      timeout=0.5)
    app.run()
    assert not app.exception, app.exception
    assert any("UNREACHABLE" in element.value for element in app.error)
