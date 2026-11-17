"""Per-vehicle simulation: movement, ignition, battery, heartbeats, and rare faults.

Pure and deterministic: a vehicle's behaviour depends only on the seed, its ID, its starting
state, and the clock. Each step returns the events the vehicle would report in that interval.
All locations and behaviour are synthetic.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .roads import LatLon, Spot, lerp, network_for

HEARTBEAT_EVERY = timedelta(minutes=5)
BATTERY_EVERY = timedelta(minutes=15)
KM_PER_DEGREE = 111.0

# Rare background faults, per vehicle per hour.
HARSH_BRAKING_PER_HOUR = 0.3   # while driving
DIAGNOSTIC_PER_HOUR = 0.01
CONNECTIVITY_DROP_PER_HOUR = 0.02
WEAK_BATTERY_SHARE = 0.02      # vehicles whose parked voltage sags below the warning line

DTC_CODES = ["P0562", "P0300", "P0171", "P0420", "U0100"]


def seeded(seed: str, *parts: str) -> random.Random:
    digest = hashlib.sha256(":".join((seed, *parts)).encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dy = (lat2 - lat1) * KM_PER_DEGREE
    dx = (lon2 - lon1) * KM_PER_DEGREE * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def bearing_to(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dy = lat2 - lat1
    dx = (lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    return math.degrees(math.atan2(dx, dy)) % 360


@dataclass
class Event:
    vehicle_id: str
    event_type: str
    observed_at: datetime
    payload: dict[str, Any]


@dataclass
class VehicleSim:
    vehicle_id: str
    region: str
    rng: random.Random
    lat: float
    lon: float
    odometer_km: float
    voltage: float
    reporting: bool                 # active vehicles report; inactive/ordered ones are silent
    can_drive: bool                 # in service; vehicles in maintenance only report heartbeats
    weak_battery: bool
    spot: Spot = field(default_factory=lambda: Spot(0, 0.5))  # where it is parked, or heading
    route: list[LatLon] = field(default_factory=list)         # waypoints left while driving
    driving: bool = False
    speed_kph: float = 0.0
    park_until: datetime | None = None
    next_heartbeat: datetime | None = None
    next_battery: datetime | None = None
    offline_until: datetime | None = None
    diagnostic_until: datetime | None = None
    scripted_until: datetime | None = None   # a scenario owns the vehicle until then
    relocated: bool = False   # resumed off-road and moved onto one: report the new position
    sequence: int = field(default=0)

    @classmethod
    def create(
        cls,
        seed: str,
        vehicle: dict[str, Any],
        start: datetime,
        resume: dict[str, Any] | None = None,
    ) -> "VehicleSim":
        rng = seeded(seed, "vehicle", vehicle["vehicleId"])
        roads = network_for(vehicle["regionCode"])
        spot = roads.random_spot(rng)
        odometer = rng.uniform(20_000, 150_000)
        location = (resume or {}).get("lastLocation") or {}
        if "latitude" in location and "longitude" in location:
            # Resume at the nearest point on the road network (older runs parked anywhere).
            spot = roads.snap((location["latitude"], location["longitude"]))
        lat, lon = roads.point(spot)
        relocated = bool(location) and distance_km(
            location.get("latitude", lat), location.get("longitude", lon), lat, lon) > 0.05
        if (resume or {}).get("odometerKm") is not None:
            odometer = resume["odometerKm"]
        weak = rng.random() < WEAK_BATTERY_SHARE
        sim = cls(
            vehicle_id=vehicle["vehicleId"],
            region=vehicle["regionCode"],
            rng=rng,
            lat=lat,
            lon=lon,
            spot=spot,
            relocated=relocated,
            odometer_km=odometer,
            voltage=rng.uniform(12.4, 12.7) if not weak else rng.uniform(11.9, 12.1),
            reporting=vehicle["lifecycleStatus"] == "active",
            can_drive=vehicle["serviceStatus"] == "in_service",
            weak_battery=weak,
        )
        # Stagger the first reports so vehicles do not all report in the same second.
        sim.next_heartbeat = start + timedelta(seconds=rng.uniform(0, 300))
        sim.next_battery = start + timedelta(seconds=rng.uniform(0, 900))
        sim.park_until = start + timedelta(minutes=rng.uniform(0, 45))
        return sim

    # ---- helpers -------------------------------------------------------------------

    def _emit(self, events: list[Event], event_type: str, at: datetime, **payload: Any) -> None:
        self.sequence += 1
        events.append(Event(self.vehicle_id, event_type, at, payload))

    def _chance(self, per_hour: float, dt: timedelta) -> bool:
        return self.rng.random() < per_hour * dt.total_seconds() / 3600

    def stop(self) -> None:
        """Park where the vehicle is now (on a road, never on a bridge)."""
        roads = network_for(self.region)
        self.spot = roads.snap((self.lat, self.lon))
        self.lat, self.lon = roads.point(self.spot)
        self.route = []
        self.driving = False
        self.speed_kph = 0.0

    def _plan_trip(self) -> None:
        """Pick a parking spot elsewhere in the region and route to it along the roads."""
        roads = network_for(self.region)
        target = roads.random_spot(self.rng)
        self.route = roads.route(self.spot, target)
        self.spot = target

    def _location(self) -> dict[str, Any]:
        return {"latitude": round(self.lat, 5), "longitude": round(self.lon, 5),
                "speedKph": round(self.speed_kph, 1), "odometerKm": round(self.odometer_km, 1)}

    # ---- simulation ----------------------------------------------------------------

    def step(self, now: datetime, dt: timedelta) -> list[Event]:
        """Advance from now - dt to now and return the events reported in that interval."""
        events: list[Event] = []
        if not self.reporting:
            return events
        if self.scripted_until and now < self.scripted_until:
            return events
        if self.offline_until:
            if now < self.offline_until:
                return events
            self.offline_until = None
            self._emit(events, "connectivity_restored", now, **self._location())

        if self.relocated:
            self.relocated = False
            self._emit(events, "location", now, **self._location())
        self._move(events, now, dt)
        self._battery(dt)

        if self.next_heartbeat and now >= self.next_heartbeat:
            self._emit(events, "heartbeat", now, odometerKm=round(self.odometer_km, 1))
            self.next_heartbeat = now + HEARTBEAT_EVERY
        if self.next_battery and now >= self.next_battery:
            self._emit(events, "battery_voltage", now, voltage=round(self.voltage, 2))
            self.next_battery = now + BATTERY_EVERY

        self._faults(events, now, dt)
        return events

    def _move(self, events: list[Event], now: datetime, dt: timedelta) -> None:
        if not self.driving:
            if self.can_drive and self.park_until and now >= self.park_until:
                self.driving = True
                self._plan_trip()
                self.speed_kph = self.rng.uniform(30, 80)
                self._emit(events, "ignition_on", now, **self._location())
            return
        travel = self.speed_kph * dt.total_seconds() / 3600
        heading = 0.0
        while travel > 0 and self.route:
            target = self.route[0]
            gap = distance_km(self.lat, self.lon, *target)
            heading = bearing_to(self.lat, self.lon, *target) if gap > 0 else heading
            if travel >= gap:
                self.lat, self.lon = target
                self.odometer_km += gap
                travel -= gap
                self.route.pop(0)
            else:
                self.lat, self.lon = lerp((self.lat, self.lon), target, travel / gap)
                self.odometer_km += travel
                travel = 0
        if not self.route:
            self.driving = False
            self.speed_kph = 0.0
            self.park_until = now + timedelta(minutes=self.rng.uniform(10, 90))
            self._emit(events, "location", now, **self._location())
            self._emit(events, "ignition_off", now, **self._location())
            return
        self.speed_kph = max(5.0, min(110.0, self.speed_kph + self.rng.uniform(-8, 8)))
        self._emit(events, "location", now, heading=round(heading), **self._location())

    def _battery(self, dt: timedelta) -> None:
        hours = dt.total_seconds() / 3600
        if self.driving:
            self.voltage = min(14.2, self.voltage + 1.5 * hours)   # alternator charging
        else:
            sag = 0.25 if self.weak_battery else 0.03                # volts per parked hour
            floor = 11.2 if self.weak_battery else 12.2
            self.voltage = max(floor, self.voltage - sag * hours)
            if self.voltage > 12.7:
                self.voltage -= 0.5 * hours                          # surface charge fades
        self.voltage += self.rng.uniform(-0.02, 0.02)

    def _faults(self, events: list[Event], now: datetime, dt: timedelta) -> None:
        if self.driving and self._chance(HARSH_BRAKING_PER_HOUR, dt):
            self._emit(events, "harsh_braking", now, **self._location())
        if self.diagnostic_until and now >= self.diagnostic_until:
            self.diagnostic_until = None
            self._emit(events, "diagnostic_cleared", now)
        elif not self.diagnostic_until and self._chance(DIAGNOSTIC_PER_HOUR, dt):
            self.diagnostic_until = now + timedelta(minutes=self.rng.uniform(30, 120))
            self._emit(events, "diagnostic_failure", now, dtcCode=self.rng.choice(DTC_CODES),
                       severity="warning")
        if self._chance(CONNECTIVITY_DROP_PER_HOUR, dt):
            self._emit(events, "heartbeat_missed", now)
            self._emit(events, "connectivity_lost", now + timedelta(seconds=30))
            self.offline_until = now + timedelta(minutes=self.rng.uniform(5, 20))
