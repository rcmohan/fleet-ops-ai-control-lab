"""Read-only calls for the fleet console. It changes nothing in the services."""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from console.backend import ServiceAPI, ServiceError

# A vehicle that has reported nothing for this long is shown as stale. Heartbeats come every
# 5 minutes, so this is three missed heartbeats.
STALE_AFTER = timedelta(minutes=15)
OPEN_INCIDENT_STATUSES = ("detected", "awaiting_approval", "case_opened")

__all__ = ["FleetBackend", "ServiceError", "STALE_AFTER", "is_stale"]


def ops_console_url() -> str:
    return os.environ.get("FLEETOPS_OPS_CONSOLE_URL", "http://127.0.0.1:8501").rstrip("/")


def parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def is_stale(state: dict[str, Any] | None, now: datetime) -> bool:
    observed = parse((state or {}).get("observedAt"))
    return observed is None or now - observed > STALE_AFTER


@dataclass
class FleetBackend(ServiceAPI):
    ops_console: str = field(default_factory=ops_console_url)

    # --- fleets

    def fleets(self) -> list[dict[str, Any]]:
        return self.get_all("fleet-master", "/v1/fleets")

    def fleet(self, fleet_id: str) -> dict[str, Any] | None:
        return self.get("fleet-master", f"/v1/fleets/{fleet_id}", missing_ok=True)

    def fleet_contract(self, fleet_id: str) -> dict[str, Any] | None:
        return self.get("fleet-master", f"/v1/fleets/{fleet_id}/contract", missing_ok=True)

    def fleet_sla(self, fleet_id: str) -> dict[str, Any] | None:
        return self.get("fleet-master", f"/v1/fleets/{fleet_id}/sla", missing_ok=True)

    def provider(self, provider_id: str) -> dict[str, Any] | None:
        return self.get("service-provider-master", f"/v1/service-providers/{provider_id}",
                        missing_ok=True)

    # --- vehicles and their live state

    def vehicles(self, fleet_id: str | None = None) -> list[dict[str, Any]]:
        return self.get_all("vehicle-master", "/v1/vehicles", {"fleet_id": fleet_id})

    def states(self, fleet_id: str | None = None) -> dict[str, dict[str, Any]]:
        """Latest digital-twin state per vehicle ID."""
        items = self.get_all("digital-twin-context", "/v1/digital-twins/vehicles",
                             {"fleet_id": fleet_id})
        return {item["vehicleId"]: item for item in items}

    def open_incidents(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for status in OPEN_INCIDENT_STATUSES:
            items += self.get_all("signal-correlation", "/v1/correlation/incidents",
                                  {"status": status})
        return items

    def fleet_rows(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """One row per fleet: master data plus live health and open-incident counts."""
        now = now or datetime.now(UTC)
        fleets = self.fleets()
        vehicles = self.vehicles()
        states = self.states()
        fleet_of = {vehicle["vehicleId"]: vehicle["fleetId"] for vehicle in vehicles}
        incidents = Counter(fleet_of.get(item["vehicleId"]) for item in self.open_incidents())
        members = Counter(vehicle["fleetId"] for vehicle in vehicles)
        health: dict[str, Counter] = {}
        for vehicle in vehicles:
            state = states.get(vehicle["vehicleId"])
            bucket = health.setdefault(vehicle["fleetId"], Counter())
            bucket["stale" if is_stale(state, now) else state["healthState"]] += 1
        rows = []
        for fleet in fleets:
            counts = health.get(fleet["fleetId"], Counter())
            rows.append({
                **fleet,
                "vehicleCount": members[fleet["fleetId"]],
                "healthy": counts["healthy"], "warning": counts["warning"],
                "critical": counts["critical"], "stale": counts["stale"],
                "openIncidents": incidents[fleet["fleetId"]],
            })
        return rows

    def vehicle_rows(self, fleet_id: str | None = None,
                     now: datetime | None = None) -> list[dict[str, Any]]:
        """Vehicles joined with their twin state (None when the twin has not seen them)."""
        now = now or datetime.now(UTC)
        states = self.states(fleet_id)
        return [
            {**vehicle, "state": states.get(vehicle["vehicleId"]),
             "stale": is_stale(states.get(vehicle["vehicleId"]), now)}
            for vehicle in self.vehicles(fleet_id)
        ]

    # --- one vehicle

    def vehicle(self, vehicle_id: str) -> dict[str, Any] | None:
        return self.get("vehicle-master", f"/v1/vehicles/{vehicle_id}", missing_ok=True)

    def unit(self, unit_id: str) -> dict[str, Any] | None:
        return self.get("telematics-unit-master", f"/v1/telematics-units/{unit_id}",
                        missing_ok=True)

    def state(self, vehicle_id: str) -> dict[str, Any] | None:
        return self.get("digital-twin-context", f"/v1/digital-twins/vehicles/{vehicle_id}",
                        missing_ok=True)

    def alerts(self, vehicle_id: str) -> list[dict[str, Any]]:
        return self.get("telematics-event", f"/v1/vehicles/{vehicle_id}/active-alerts")["alerts"]

    def recent_events(self, vehicle_id: str, hours: int = 24, limit: int = 100,
                      now: datetime | None = None) -> list[dict[str, Any]]:
        now = now or datetime.now(UTC)
        page = self.get("telematics-event", f"/v1/vehicles/{vehicle_id}/events", params={
            "from": (now - timedelta(hours=hours)).isoformat(), "to": now.isoformat(),
            "limit": limit,
        })
        return page["items"]

    def maintenance(self, vehicle_id: str) -> list[dict[str, Any]]:
        return self.get_all("maintenance-history",
                            f"/v1/vehicles/{vehicle_id}/maintenance-records")

    def incidents(self, vehicle_id: str) -> list[dict[str, Any]]:
        return self.get_all("signal-correlation", "/v1/correlation/incidents",
                            {"vehicle_id": vehicle_id})

    def case_status(self, case_id: str) -> dict[str, Any] | None:
        return self.get("case-management", f"/v1/cases/{case_id}/status", missing_ok=True)

    def incident_link(self, incident_id: str) -> str:
        return f"{self.ops_console}/?incident={incident_id}"
