"""The dashboard snapshot (status.json): every section, partial failure, and publishing."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from cloud_exporter.app import build_app
from cloud_exporter.dashboard import SCHEMA, Dashboard, build_status, voltage_bins
from cloud_exporter.exporter import Exporter
from cloud_exporter.sinks import FileSink
from fleetops_runtime.services import ServiceClients

NOW = datetime(2026, 11, 18, 9, 30, tzinfo=UTC)


def at(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


def twin(vehicle_id, health, voltage, minutes_ago=1, issues=()):
    return {"vehicleId": vehicle_id, "fleetId": "flt_1", "healthState": health,
            "connectivityState": "connected", "batteryVoltage": voltage,
            "activeIssues": [{"issue": issue} for issue in issues],
            "observedAt": at(minutes_ago)}


class Services:
    def __init__(self) -> None:
        self.vehicles = [
            {"vehicleId": "veh_1", "fleetId": "flt_1", "regionCode": "us-east",
             "lifecycleStatus": "active"},
            {"vehicleId": "veh_2", "fleetId": "flt_1", "regionCode": "us-east",
             "lifecycleStatus": "active"},
            {"vehicleId": "veh_3", "fleetId": "flt_2", "regionCode": "eu-west",
             "lifecycleStatus": "active"},
            {"vehicleId": "veh_4", "fleetId": "flt_2", "regionCode": "eu-west",
             "lifecycleStatus": "active"},
            {"vehicleId": "veh_9", "fleetId": "flt_2", "regionCode": "eu-west",
             "lifecycleStatus": "retired"},
        ]
        self.twins = [
            twin("veh_1", "healthy", 12.6),
            twin("veh_2", "critical", 11.5, issues=("battery",)),
            twin("veh_3", "warning", 11.9),
            twin("veh_4", "healthy", 12.7, minutes_ago=40),   # stale
        ]
        self.fleets = [{"fleetId": "flt_1", "customerName": "Northstar", "slaLevel": "gold"},
                       {"fleetId": "flt_2", "customerName": "Harbor", "slaLevel": "standard"}]
        # Newest first, as signal-correlation lists them; the last is outside the 24 h window.
        self.incidents = [
            {"incidentId": "inc_3", "vehicleId": "veh_2", "status": "case_opened",
             "caseId": "case_1", "riskScore": 71.0, "riskLevel": "high",
             "policyDecision": "allowed", "ruleId": "r", "detectedAt": at(20)},
            {"incidentId": "inc_2", "vehicleId": "veh_3", "status": "awaiting_approval",
             "caseId": None, "detectedAt": at(90)},
            {"incidentId": "inc_1", "vehicleId": "veh_1", "status": "closed",
             "caseId": None, "detectedAt": at(60 * 30)},
        ]
        self.down: set[str] = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        host, path, params = request.url.host, request.url.path, request.url.params
        if host in self.down:
            raise httpx.ConnectError("refused", request=request)
        if path == "/v1/status":
            return httpx.Response(200, json={"services": [
                {"name": "vehicle-master", "status": "healthy", "version": "0.1.0",
                 "samples": [[1, 2.0, "healthy"], [2, 4.0, "healthy"]]},
                {"name": "approval", "status": "down", "version": None,
                 "samples": [[1, 3.0, "healthy"], [2, None, "down"]]},
            ]})
        if path.startswith("/v1/correlation/incidents/"):
            incident_id = path.rsplit("/", 1)[1]
            item = next(i for i in self.incidents if i["incidentId"] == incident_id)
            timeline = [{"step": "detected", "at": item["detectedAt"]}]
            if item["caseId"]:
                timeline += [{"step": "scored", "at": at(19)}, {"step": "case_opened", "at": at(17.5)}]
            return httpx.Response(200, json={**item, "timeline": timeline})
        if path == "/v1/correlation/incidents":
            items = self.incidents
            if "status" in params:
                items = [i for i in items if i["status"] == params["status"]]
            start = int(params.get("cursor") or 0)
            return httpx.Response(200, json={"items": items[start:start + 2],
                                             "nextCursor": str(start + 2)
                                             if start + 2 < len(items) else ""})
        items = {"/v1/vehicles": self.vehicles, "/v1/digital-twins/vehicles": self.twins,
                 "/v1/fleets": self.fleets}[path]
        return httpx.Response(200, json={"items": items, "nextCursor": None})


def clients(services: Services) -> ServiceClients:
    return ServiceClients(transport=httpx.MockTransport(services))


@pytest.mark.anyio
async def test_snapshot_summarises_fleet_incidents_and_services() -> None:
    status = await build_status(clients(Services()), NOW)
    assert status["schema"] == SCHEMA and status["synthetic"] and status["errors"] == []
    assert status["summary"] == {
        "vehicles": 4, "healthy": 1, "warning": 1, "critical": 1, "stale": 1, "reporting": 3,
        "openIncidents": 2, "incidents24h": 2, "casesOpened24h": 1,
        "medianMinutesToCase": 2.5, "caseTimingSample": 1,
        "servicesHealthy": 1, "servicesTotal": 2,
    }
    assert status["regions"] == [
        {"regionCode": "eu-west", "vehicles": 2, "healthy": 0, "warning": 1, "critical": 0,
         "stale": 1},
        {"regionCode": "us-east", "vehicles": 2, "healthy": 1, "warning": 0, "critical": 1,
         "stale": 0},
    ]
    # Stale vehicles' last readings are not counted as current battery state.
    assert status["battery"]["reporting"] == 3
    assert [b["vehicles"] for b in status["battery"]["bins"]] == [0, 1, 1, 0, 1, 0]
    hours = status["incidentsByHour"]
    assert len(hours) == 24 and hours[-1]["hour"] == "2026-11-18T09:00:00Z"
    assert sum(h["detected"] for h in hours) == 2
    first = status["recentIncidents"][0]
    assert first["incidentId"] == "inc_3" and first["regionCode"] == "us-east"
    assert first["minutesToCase"] == 2.5 and first["steps"] == ["detected", "scored",
                                                                 "case_opened"]
    assert [v["vehicleId"] for v in status["attention"]] == ["veh_2", "veh_3", "veh_4"]
    assert status["attention"][0]["issues"] == ["battery"]
    assert status["fleets"][0]["fleetId"] == "flt_1" and status["fleets"][0]["openIncidents"] == 1
    assert status["services"][1] == {"name": "approval", "status": "down", "version": None,
                                     "uptimePct": 50.0, "latencyMsP50": 3.0}


@pytest.mark.anyio
async def test_a_down_service_empties_only_its_sections() -> None:
    services = Services()
    services.down.update({"status-monitor", "signal-correlation"})
    status = await build_status(clients(services), NOW)
    assert {e["section"] for e in status["errors"]} == {"services", "incidents",
                                                        "openIncidents"}
    assert status["summary"]["vehicles"] == 4 and status["services"] == []
    assert status["recentIncidents"] == [] and status["summary"]["incidents24h"] == 0


def test_voltage_bins_split_at_the_low_voltage_line() -> None:
    bins = voltage_bins([11.0, 11.79, 11.8, 13.5])
    assert [b["label"] for b in bins] == ["< 11.4", "11.4–11.8", "11.8–12.2", "12.2–12.6",
                                          "12.6–13.0", "≥ 13.0"]
    assert [b["vehicles"] for b in bins] == [1, 1, 1, 0, 0, 1]
    assert [b["low"] for b in bins] == [True, True, False, False, False, False]


class FakeUploader:
    bucket, name = "demo-bucket", "status.json"

    def __init__(self) -> None:
        self.uploads: list[dict] = []

    def upload(self, data: bytes) -> None:
        self.uploads.append(json.loads(data))


@pytest.mark.anyio
async def test_refresh_writes_the_file_and_uploads_it(tmp_path) -> None:
    uploader = FakeUploader()
    dashboard = Dashboard(clients(Services()), directory=tmp_path, uploader=uploader,
                          clock=lambda: NOW)
    status = await dashboard.refresh()
    assert json.loads((tmp_path / "status.json").read_text(encoding="utf-8")) == status
    assert uploader.uploads == [status]
    assert dashboard.describe()["bucket"] == "gs://demo-bucket/status.json"


def test_exporter_serves_the_latest_snapshot(tmp_path) -> None:
    services = Services()
    dashboard = Dashboard(clients(services), clock=lambda: NOW)
    exporter = Exporter(FileSink(tmp_path), clients(services), context_interval=0,
                        events_interval=0, flush_interval=0, dashboard=dashboard)
    with TestClient(build_app(exporter, run_background=False)) as client:
        response = client.get("/v1/dashboard/status.json")
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert response.json()["summary"]["vehicles"] == 4
        assert client.get("/v1/exports/status").json()["dashboard"]["generatedAt"] == \
            "2026-11-18T09:30:00Z"
    disabled = Exporter(FileSink(tmp_path), clients(services), context_interval=0)
    with TestClient(build_app(disabled, run_background=False)) as client:
        assert client.get("/v1/dashboard/status.json").status_code == 404
