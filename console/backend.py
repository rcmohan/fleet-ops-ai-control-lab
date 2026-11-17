"""Server-side calls for the operations console.

The browser never talks to the services. In particular it never supplies a reviewer identity:
the console sends X-Reviewer-Id itself, and only for reviewers on its configured allowlist.
There is no login yet, so anyone who can open the console can act as any allowlisted
reviewer. That is acceptable only because the console is bound to 127.0.0.1. A deployment
must put an authenticated access layer in front and map its verified identity to a reviewer.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from fleetops_sim.model import VehicleSim
from fleetops_sim.runner import event_id, iso
from fleetops_sim.scenarios import SCENARIOS

DEFAULT_REVIEWERS = ("reviewer_ops_001", "reviewer_safety_001")
INCIDENT_STATUSES = (
    "detected", "awaiting_approval", "case_opened", "rejected", "approval_expired",
    "blocked", "failed", "closed",
)


class ServiceError(Exception):
    """A service answered with an error (or could not be reached)."""

    def __init__(self, service: str, status: int, code: str, message: str) -> None:
        super().__init__(f"{service}: {code}: {message}")
        self.service, self.status, self.code, self.message = service, status, code, message


def service_urls() -> Callable[[str], str]:
    """FLEETOPS_CONSOLE_GATEWAY routes every call through the gateway (for running the console
    outside Compose); otherwise each service is reached directly, as the services do."""
    gateway = os.environ.get("FLEETOPS_CONSOLE_GATEWAY", "").rstrip("/")
    if gateway:
        return lambda slug: f"{gateway}/{slug}"

    def service_url(slug: str) -> str:  # same rule as fleetops_runtime.services.service_url
        env = "FLEETOPS_" + slug.upper().replace("-", "_") + "_URL"
        return os.environ.get(env, f"http://{slug}:8080").rstrip("/")

    return service_url


def configured_reviewers() -> tuple[str, ...]:
    raw = os.environ.get("FLEETOPS_CONSOLE_REVIEWERS", "")
    reviewers = tuple(item.strip() for item in raw.split(",") if item.strip())
    return reviewers or DEFAULT_REVIEWERS


@dataclass
class Backend:
    url_for: Callable[[str], str] = field(default_factory=service_urls)
    reviewers: tuple[str, ...] = field(default_factory=configured_reviewers)
    transport: httpx.BaseTransport | None = None
    timeout: float = 5.0

    def __post_init__(self) -> None:
        self.http = httpx.Client(transport=self.transport, timeout=self.timeout)

    def close(self) -> None:
        self.http.close()

    # --- plumbing

    def call(self, method: str, slug: str, path: str, *, missing_ok: bool = False,
             **kwargs: Any) -> Any:
        try:
            response = self.http.request(method, self.url_for(slug) + path, **kwargs)
        except httpx.HTTPError as exc:
            raise ServiceError(slug, 0, "UNREACHABLE", type(exc).__name__) from exc
        if response.status_code == 404 and missing_ok:
            return None
        if response.status_code >= 400:
            code, message = f"HTTP_{response.status_code}", response.text[:300]
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = None
            if isinstance(detail, dict):
                code, message = detail.get("code", code), detail.get("message", message)
            elif isinstance(detail, list) and detail:
                code, message = "VALIDATION", str(detail[0].get("msg", detail[0]))
            raise ServiceError(slug, response.status_code, code, message)
        return response.json()

    def get(self, slug: str, path: str, **kwargs: Any) -> Any:
        return self.call("GET", slug, path, **kwargs)

    # --- incidents

    def incidents(self, status: str | None = None, vehicle_id: str | None = None,
                  limit: int = 200) -> list[dict[str, Any]]:
        params = {"limit": limit, "status": status, "vehicle_id": vehicle_id}
        page = self.get("signal-correlation", "/v1/correlation/incidents",
                        params={k: v for k, v in params.items() if v})
        return page["items"]

    def incident(self, incident_id: str) -> dict[str, Any]:
        return self.get("signal-correlation", f"/v1/correlation/incidents/{incident_id}")

    def close_incident(self, incident_id: str, reason: str) -> dict[str, Any]:
        return self.call("POST", "signal-correlation",
                         f"/v1/correlation/incidents/{incident_id}/close", json={"reason": reason})

    def rules(self) -> list[dict[str, Any]]:
        return self.get("signal-correlation", "/v1/correlation/rules")["items"]

    def trace(self, trace_id: str) -> list[dict[str, Any]]:
        found = self.get("audit-observability", f"/v1/traces/{trace_id}", missing_ok=True)
        return found["events"] if found else []

    # --- vehicle evidence

    def vehicle_context(self, vehicle_id: str) -> dict[str, Any] | None:
        return self.get("vehicle-context-facade", f"/v1/vehicle-context/{vehicle_id}",
                        missing_ok=True)

    def twin(self, vehicle_id: str) -> dict[str, Any] | None:
        return self.get("digital-twin-context", f"/v1/digital-twins/vehicles/{vehicle_id}",
                        missing_ok=True)

    def active_alerts(self, vehicle_id: str) -> list[dict[str, Any]]:
        return self.get("telematics-event", f"/v1/vehicles/{vehicle_id}/active-alerts")["alerts"]

    # --- approvals and cases

    def approval(self, approval_id: str) -> dict[str, Any] | None:
        return self.get("approval", f"/v1/approvals/{approval_id}", missing_ok=True)

    def pending_approvals(self, reviewer_id: str) -> list[dict[str, Any]]:
        self._check_reviewer(reviewer_id)
        return self.get("approval", "/v1/approvals",
                        params={"reviewer_id": reviewer_id, "limit": 200})["items"]

    def decide(self, approval_id: str, decision: str, comments: str | None,
               reviewer_id: str) -> dict[str, Any]:
        self._check_reviewer(reviewer_id)
        if decision not in ("approved", "rejected"):
            raise ValueError(f"unknown decision {decision!r}")
        return self.call(
            "POST", "approval", f"/v1/approvals/{approval_id}/decisions",
            json={"decision": decision, "comments": comments or None},
            headers={"X-Reviewer-Id": reviewer_id},
        )

    def case_status(self, case_id: str) -> dict[str, Any] | None:
        return self.get("case-management", f"/v1/cases/{case_id}/status", missing_ok=True)

    def assign_case(self, case_id: str, team_id: str) -> dict[str, Any]:
        return self.call("PUT", "case-management", f"/v1/cases/{case_id}/assignment",
                         json={"teamId": team_id})

    def update_case(self, case_id: str, status: str, comment: str | None = None,
                    resolution: str | None = None, root_cause: str | None = None) -> dict[str, Any]:
        body = {"status": status, "comment": comment or None}
        if status == "resolved":
            body.update(resolution=resolution or None, rootCause=root_cause or None)
        return self.call("PUT", "case-management", f"/v1/cases/{case_id}/status", json=body)

    def _check_reviewer(self, reviewer_id: str) -> None:
        if reviewer_id not in self.reviewers:
            raise PermissionError(f"{reviewer_id} is not a reviewer this console may act as")

    # --- scenario injection

    def inject(self, vehicle_id: str, scenario: str = "battery_connectivity",
               now: datetime | None = None) -> list[dict[str, Any]]:
        """Send a scripted fault for one vehicle that ends just before now. Each injection
        gets fresh event IDs, so injecting twice produces two occurrences."""
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario {scenario!r}")
        vehicle = self.get("vehicle-master", f"/v1/vehicles/{vehicle_id}", missing_ok=True)
        if vehicle is None:
            raise ServiceError("vehicle-master", 404, "NOT_FOUND", f"vehicle {vehicle_id} not found")
        now = (now or datetime.now(UTC)).replace(microsecond=0)
        start = now - timedelta(minutes=10)
        sim = VehicleSim.create("console", vehicle, start)
        script = SCENARIOS[scenario](sim, start)
        seed = f"console-{now.isoformat()}"
        results = []
        for event in script:
            body = {"eventId": event_id(seed, event), "vehicleId": event.vehicle_id,
                    "eventType": event.event_type, "observedAt": iso(event.observed_at),
                    "payload": event.payload}
            receipt = self.call("POST", "telematics-event", "/v1/events", json=body)
            results.append({**body, "status": receipt["status"]})
        return results
