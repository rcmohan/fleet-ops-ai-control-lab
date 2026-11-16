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

# Synthetic operating areas: a centre point and radius per region code.
REGION_AREAS: dict[str, tuple[float, float, float]] = {
    "us-east": (40.71, -74.00, 60.0),
    "us-central": (41.88, -87.63, 60.0),
    "us-west": (37.77, -122.42, 60.0),
    "us-south": (29.76, -95.37, 60.0),
    "ca-east": (43.65, -79.38, 50.0),
    "ca-west": (49.28, -123.12, 40.0),
    "eu-west": (51.51, -0.13, 50.0),
    "eu-central": (50.11, 8.68, 50.0),
}
DEFAULT_AREA = (40.71, -74.00, 60.0)

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


def offset(lat: float, lon: float, bearing_deg: float, km: float) -> tuple[float, float]:
    bearing = math.radians(bearing_deg)
    new_lat = lat + (km * math.cos(bearing)) / KM_PER_DEGREE
    new_lon = lon + (km * math.sin(bearing)) / (KM_PER_DEGREE * math.cos(math.radians(lat)))
    return new_lat, new_lon


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
    driving: bool = False
    destination: tuple[float, float] | None = None
    speed_kph: float = 0.0
    park_until: datetime | None = None
    next_heartbeat: datetime | None = None
    next_battery: datetime | None = None
    offline_until: datetime | None = None
    diagnostic_until: datetime | None = None
    scripted_until: datetime | None = None   # a scenario owns the vehicle until then
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
        clat, clon, radius = REGION_AREAS.get(vehicle["regionCode"], DEFAULT_AREA)
        lat, lon = offset(clat, clon, rng.uniform(0, 360), rng.uniform(0, radius))
        odometer = rng.uniform(20_000, 150_000)
        location = (resume or {}).get("lastLocation") or {}
        if "latitude" in location and "longitude" in location:
            lat, lon = location["latitude"], location["longitude"]
        if (resume or {}).get("odometerKm") is not None:
            odometer = resume["odometerKm"]
        weak = rng.random() < WEAK_BATTERY_SHARE
        sim = cls(
            vehicle_id=vehicle["vehicleId"],
            region=vehicle["regionCode"],
            rng=rng,
            lat=lat,
            lon=lon,
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

    def _pick_destination(self) -> tuple[float, float]:
        clat, clon, radius = REGION_AREAS.get(self.region, DEFAULT_AREA)
        return offset(clat, clon, self.rng.uniform(0, 360), self.rng.uniform(0, radius))

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
                self.destination = self._pick_destination()
                self.speed_kph = self.rng.uniform(30, 80)
                self._emit(events, "ignition_on", now, **self._location())
            return
        assert self.destination is not None
        remaining = distance_km(self.lat, self.lon, *self.destination)
        travel = self.speed_kph * dt.total_seconds() / 3600
        if travel >= remaining:
            self.lat, self.lon = self.destination
            self.odometer_km += remaining
            self.driving = False
            self.speed_kph = 0.0
            self.park_until = now + timedelta(minutes=self.rng.uniform(10, 90))
            self._emit(events, "location", now, **self._location())
            self._emit(events, "ignition_off", now, **self._location())
            return
        heading = bearing_to(self.lat, self.lon, *self.destination)
        self.lat, self.lon = offset(self.lat, self.lon, heading, travel)
        self.odometer_km += travel
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
