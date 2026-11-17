"""Road networks: on land, connected, and used for parking, routing and resuming."""

import random
from datetime import UTC, datetime, timedelta

import pytest

from fleetops_sim import VehicleSim
from fleetops_sim.roads import NETWORKS, Spot, distance_km, lerp

STEP_KM = 0.1
MAX_CROSSING_WATER_KM = 6.0


@pytest.mark.parametrize("region", sorted(NETWORKS))
def test_network_is_on_land_except_crossings(region: str) -> None:
    globe = pytest.importorskip("global_land_mask.globe")
    roads = NETWORKS[region]
    for name, (lat, lon) in roads.nodes.items():
        assert globe.is_land(lat, lon), f"{region}: {name} is in water"
    for edge in roads.edges:
        a, b = roads.nodes[edge.a], roads.nodes[edge.b]
        steps = max(2, int(distance_km(a, b) / STEP_KM))
        wet = sum(not globe.is_land(*lerp(a, b, i / steps)) for i in range(steps + 1))
        water_km = wet * distance_km(a, b) / steps
        if edge.crossing:
            assert water_km <= MAX_CROSSING_WATER_KM, f"{region}: {edge} crosses {water_km:.1f} km"
        else:
            assert wet == 0, f"{region}: road {edge.a}-{edge.b} touches water"


@pytest.mark.parametrize("region", sorted(NETWORKS))
def test_network_is_connected(region: str) -> None:
    roads = NETWORKS[region]
    start = next(iter(roads.nodes))
    reached, stack = {start}, [start]
    while stack:
        for neighbour, _ in roads.adjacency[stack.pop()]:
            if neighbour not in reached:
                reached.add(neighbour)
                stack.append(neighbour)
    assert reached == set(roads.nodes)


def test_parking_never_on_crossings_and_routes_follow_edges() -> None:
    rng = random.Random(7)
    roads = NETWORKS["us-west"]
    for _ in range(200):
        origin, target = roads.random_spot(rng), roads.random_spot(rng)
        assert not roads.edges[origin.edge].crossing
        waypoints = roads.route(origin, target)
        assert waypoints[-1] == roads.point(target)
        # Every intermediate waypoint is a node, and consecutive nodes share an edge.
        nodes = {coords: name for name, coords in roads.nodes.items()}
        names = [nodes[point] for point in waypoints[:-1]]
        for first, second in zip(names, names[1:]):
            assert second in {n for n, _ in roads.adjacency[first]}


def test_snap_moves_a_position_in_water_onto_a_road() -> None:
    roads = NETWORKS["us-east"]
    raritan_bay = (40.47, -74.13)  # where the old simulator parked some vehicles
    spot = roads.snap(raritan_bay)
    assert isinstance(spot, Spot) and not roads.edges[spot.edge].crossing
    assert 0.05 <= spot.t <= 0.95


def test_vehicle_resumed_in_water_starts_on_a_road() -> None:
    start = datetime(2026, 11, 17, 8, 0, tzinfo=UTC)
    vehicle = {"vehicleId": "veh_0001", "regionCode": "us-east", "lifecycleStatus": "active",
               "serviceStatus": "in_service"}
    sim = VehicleSim.create("s", vehicle, start,
                            resume={"lastLocation": {"latitude": 40.47, "longitude": -74.13}})
    roads = NETWORKS["us-east"]
    assert (sim.lat, sim.lon) == roads.point(sim.spot)
    assert not roads.edges[sim.spot.edge].crossing
    # It reports the corrected position straight away, even if it is not about to drive.
    first = sim.step(start + timedelta(minutes=1), timedelta(minutes=1))
    location = next(e for e in first if e.event_type == "location")
    assert (location.payload["latitude"], location.payload["longitude"]) == (
        round(sim.lat, 5), round(sim.lon, 5))
    on_road = VehicleSim.create("s", vehicle, start, resume={"lastLocation": {
        "latitude": sim.lat, "longitude": sim.lon}})
    assert not on_road.relocated  # already on a road: nothing extra to report
