"""Scripted incidents injected into a simulation run.

battery_connectivity reproduces the MVP correlation rule battery-connectivity-v1: a
low-battery reading below 11.8 V, then a missed heartbeat, then a diagnostic failure, with
the first and last within 12 minutes. Afterwards the vehicle stays degraded: it resumes
heartbeats but its battery keeps reading low.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from .model import Event, VehicleSim


def battery_connectivity(vehicle: VehicleSim, at: datetime) -> list[Event]:
    vehicle.driving = False
    vehicle.speed_kph = 0.0
    vehicle.weak_battery = True
    vehicle.voltage = 11.3
    vehicle.scripted_until = at + timedelta(minutes=12)
    vehicle.park_until = at + timedelta(hours=6)          # stays parked after the fault
    vehicle.next_heartbeat = vehicle.scripted_until       # first report after the script
    vehicle.next_battery = vehicle.scripted_until + timedelta(minutes=3)
    script = [
        (0, "battery_voltage", {"voltage": 11.6}),
        (3, "battery_voltage", {"voltage": 11.4}),
        (5, "heartbeat_missed", {}),
        (9, "diagnostic_failure", {"dtcCode": "P0562", "severity": "critical"}),
    ]
    return [
        Event(vehicle.vehicle_id, event_type, at + timedelta(minutes=minutes), payload)
        for minutes, event_type, payload in script
    ]


SCENARIOS: dict[str, Callable[[VehicleSim, datetime], list[Event]]] = {
    "battery_connectivity": battery_connectivity,
}
