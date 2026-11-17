"""Simulator checks that need no database."""

import json
import math
import sys
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from fleetops_sim import Injection, RunConfig, Simulator, VehicleSim
from fleetops_sim.roads import NETWORKS, distance_km, lerp
from fleetops_sim.scenarios import battery_connectivity

from conftest import all_services

all_services()  # registers the service handler modules
EVENTS = sys.modules["telematics_event_handlers"]

START = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
TICK = timedelta(minutes=1)


def vehicle(n: int, region: str = "us-east", **overrides) -> dict:
    return {"vehicleId": f"veh_{n:04d}", "regionCode": region, "lifecycleStatus": "active",
            "serviceStatus": "in_service", **overrides}


def off_road_km(region: str, lat: float, lon: float) -> float:
    """Distance from the nearest edge of the region's road network."""
    roads = NETWORKS[region]
    best = float("inf")
    for edge in roads.edges:
        a, b = roads.nodes[edge.a], roads.nodes[edge.b]
        scale = math.cos(math.radians(a[0]))
        dx, dy = (b[1] - a[1]) * scale, b[0] - a[0]
        px, py = (lon - a[1]) * scale, lat - a[0]
        t = max(0.0, min(1.0, (px * dx + py * dy) / (dx * dx + dy * dy)))
        best = min(best, distance_km((lat, lon), lerp(a, b, t)))
    return best


def run_model(sim: VehicleSim, minutes: int) -> list:
    events, now = [], START
    for _ in range(minutes):
        now += TICK
        events += sim.step(now, TICK)
    return events


def test_model_is_deterministic() -> None:
    first = run_model(VehicleSim.create("s", vehicle(1), START), 240)
    second = run_model(VehicleSim.create("s", vehicle(1), START), 240)
    assert [(e.event_type, e.observed_at, e.payload) for e in first] == [
        (e.event_type, e.observed_at, e.payload) for e in second
    ]
    other = run_model(VehicleSim.create("other-seed", vehicle(1), START), 240)
    assert [e.payload for e in other] != [e.payload for e in first]


def test_events_are_valid_for_telematics_event() -> None:
    seen = set()
    for n in range(1, 41):
        region = list(NETWORKS)[n % len(NETWORKS)]
        sim = VehicleSim.create("s", vehicle(n, region), START)
        odometer = sim.odometer_km
        for event in run_model(sim, 8 * 60):
            seen.add(event.event_type)
            EVENTS.IngestEvent.model_validate({
                "vehicleId": event.vehicle_id, "eventType": event.event_type,
                "observedAt": event.observed_at.isoformat(), "payload": event.payload,
            })
            EVENTS.validate_payload(event.event_type, event.payload)
            if "odometerKm" in event.payload:
                assert event.payload["odometerKm"] >= round(odometer, 1) - 0.1
                odometer = event.payload["odometerKm"]
            if "latitude" in event.payload:  # always on the region's roads
                assert off_road_km(region, event.payload["latitude"],
                                   event.payload["longitude"]) < 0.05
    assert {"location", "heartbeat", "battery_voltage", "ignition_on", "ignition_off"} <= seen


def test_heartbeats_every_five_minutes_and_silent_vehicles() -> None:
    events = run_model(VehicleSim.create("s", vehicle(7), START), 60)
    assert 11 <= sum(e.event_type == "heartbeat" for e in events) <= 13
    parked = VehicleSim.create("s", vehicle(8, serviceStatus="maintenance"), START)
    parked_events = run_model(parked, 120)
    assert not {"location", "ignition_on"} & {e.event_type for e in parked_events}
    assert any(e.event_type == "heartbeat" for e in parked_events)
    inactive = VehicleSim.create("s", vehicle(9, lifecycleStatus="inactive"), START)
    assert run_model(inactive, 120) == []


def test_battery_connectivity_scenario_meets_the_correlation_rule() -> None:
    sim = VehicleSim.create("s", vehicle(1), START)
    at = START + timedelta(minutes=10)
    script = battery_connectivity(sim, at)
    kinds = [e.event_type for e in script]
    low = next(e for e in script if e.event_type == "battery_voltage")
    missed = next(e for e in script if e.event_type == "heartbeat_missed")
    diagnostic = next(e for e in script if e.event_type == "diagnostic_failure")
    assert low.payload["voltage"] < 11.8
    assert low.observed_at < missed.observed_at < diagnostic.observed_at
    assert diagnostic.observed_at - low.observed_at <= timedelta(minutes=12)
    assert kinds.count("diagnostic_failure") == 1
    # While scripted, the vehicle reports nothing else; it resumes at the 12-minute mark.
    now, during = at, []
    while now + TICK < at + timedelta(minutes=12):
        now += TICK
        during += sim.step(now, TICK)
    assert during == []
    # Afterwards it reports again, with a battery still under the warning line.
    after = run_model(sim, 40)
    readings = [e.payload["voltage"] for e in after if e.event_type == "battery_voltage"]
    assert readings and max(readings) < 11.8


@pytest.mark.anyio
async def test_runner_never_sends_future_events_and_retries_with_same_id() -> None:
    clock_now = START + timedelta(minutes=30)
    posted: list[dict] = []
    attempts: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/v1/vehicles"):
            return httpx.Response(200, json={"items": [vehicle(n) for n in range(1, 6)],
                                             "nextCursor": ""})
        if "/digital-twins/vehicles/" in path:
            return httpx.Response(404, json={"detail": {"code": "NOT_FOUND"}})
        body = json.loads(request.content)
        attempts[body["eventId"]] = attempts.get(body["eventId"], 0) + 1
        if attempts[body["eventId"]] == 1 and len(attempts) % 7 == 0:
            return httpx.Response(503, json={"detail": {"code": "DEPENDENCY_UNAVAILABLE"}})
        posted.append(body)
        return httpx.Response(200, json={"eventId": body["eventId"], "status": "accepted",
                                         "acceptedAt": "x"})

    config = RunConfig(start=START, minutes=30, late_share=0.2,
                       injections=[Injection("battery_connectivity", "veh_0003", 5)])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        simulator = Simulator(client, lambda slug: f"http://{slug}", config,
                              clock=lambda: clock_now)
        stats = await simulator.run()

    assert stats.outcome["accepted"] == len(posted) and "failed" not in stats.outcome
    assert any(count > 1 for count in attempts.values())  # some events needed a retry
    assert len({body["eventId"] for body in posted}) == len(posted)
    observed = [datetime.fromisoformat(body["observedAt"].replace("Z", "+00:00"))
                for body in posted]
    assert max(observed) <= clock_now
    golden = [body["eventType"] for body in posted if body["vehicleId"] == "veh_0003"]
    assert {"heartbeat_missed", "diagnostic_failure"} <= set(golden)
