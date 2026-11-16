"""Scoring policy risk-v1: deterministic, explainable point scores (0-100) from other services.

Synthetic weights for demonstration; they are not a calibrated safety or contractual model.
Confidence is the share of inputs that were available, not a model probability.
"""

from collections.abc import Awaitable
from typing import Any

from fleetops_runtime import HandlerRegistry, RequestContext
from fleetops_runtime.errors import DependencyUnavailable, invalid, not_found

HANDLERS = HandlerRegistry()

POLICY_VERSION = "risk-v1"
SEVERITY_POINTS = {"info": 10, "warning": 40, "critical": 70}
PRIORITY_POINTS = {"low": 0, "standard": 5, "high": 15, "critical": 25}
HEALTH_POINTS = {"healthy": 0, "warning": 10, "critical": 25}
SLA_POINTS = {"standard": 15, "enhanced": 30, "mission_critical": 50}
TIER_POINTS = {"basic": 10, "standard": 20, "premium": 30, "enterprise": 40}
SAFETY_POINTS = {
    "collision_detected": {"critical": 90},
    "harsh_braking": {"warning": 45},
    "battery_voltage": {"critical": 60, "warning": 30},
    "diagnostic_failure": {"critical": 60, "warning": 25},
    "heartbeat_missed": {"warning": 15},
    "connectivity_lost": {"warning": 15},
}
COMPOSITE_WEIGHTS = {"event": 0.35, "safety": 0.35, "sla": 0.30}


def level(score: float) -> str:
    if score < 25:
        return "low"
    if score < 50:
        return "medium"
    if score < 75:
        return "high"
    return "critical"


class Inputs:
    """Fetches inputs once per request and records which optional ones were unavailable."""

    def __init__(self, ctx: RequestContext) -> None:
        self.ctx = ctx
        self.expected = 0
        self.available = 0

    async def optional(self, call: Awaitable[Any]) -> Any:
        self.expected += 1
        try:
            value = await call
        except DependencyUnavailable:
            return None
        if value is not None:
            self.available += 1
        return value

    def confidence(self) -> float:
        return round((1 + self.available) / (1 + self.expected), 2)

    async def event(self, event_id: str) -> dict[str, Any]:
        event = await self.ctx.services.get("telematics-event", f"/v1/events/{event_id}")
        if event is None:
            raise not_found("event", event_id)
        return event

    def vehicle(self, vehicle_id: str) -> Awaitable[Any]:
        return self.optional(self.ctx.services.get("vehicle-master", f"/v1/vehicles/{vehicle_id}"))

    def twin(self, vehicle_id: str) -> Awaitable[Any]:
        return self.optional(
            self.ctx.services.get("digital-twin-context", f"/v1/digital-twins/vehicles/{vehicle_id}")
        )


def result(score: float, factors: list[dict[str, Any]], confidence: float) -> dict[str, Any]:
    score = round(min(max(score, 0.0), 100.0), 1)
    return {
        "score": score,
        "level": level(score),
        "confidence": confidence,
        "factors": factors,
        "scoringPolicyVersion": POLICY_VERSION,
    }


def factor(name: str, points: float, detail: str) -> dict[str, Any]:
    return {"name": name, "contribution": float(points), "detail": detail}


async def event_risk(inputs: Inputs, event: dict[str, Any]) -> dict[str, Any]:
    factors = [factor("severity", SEVERITY_POINTS[event["severity"]], event["severity"])]
    alerts = await inputs.optional(inputs.ctx.services.get(
        "telematics-event", f"/v1/vehicles/{event['vehicleId']}/active-alerts"
    ))
    if alerts is not None:
        others = [a for a in alerts["alerts"] if a["eventId"] != event["eventId"]]
        if others:
            factors.append(factor("other_active_alerts", min(5 * len(others), 15),
                                  f"{len(others)} other active alerts"))
    vehicle = await inputs.vehicle(event["vehicleId"])
    if vehicle is not None and PRIORITY_POINTS[vehicle["priorityLevel"]]:
        factors.append(factor("vehicle_priority", PRIORITY_POINTS[vehicle["priorityLevel"]],
                              vehicle["priorityLevel"]))
    total = sum(item["contribution"] for item in factors)
    return result(total, factors, inputs.confidence())


async def safety_risk(inputs: Inputs, event: dict[str, Any]) -> dict[str, Any]:
    points = SAFETY_POINTS.get(event["eventType"], {}).get(event["severity"], 5)
    factors = [factor("event_type", points, f"{event['eventType']} ({event['severity']})")]
    twin = await inputs.twin(event["vehicleId"])
    if twin is not None and twin["healthState"] != "healthy":
        bonus = 10 if twin["healthState"] == "critical" else 5
        factors.append(factor("vehicle_health", bonus, twin["healthState"]))
    total = sum(item["contribution"] for item in factors)
    return result(total, factors, inputs.confidence())


async def sla_risk(inputs: Inputs, vehicle_id: str, fleet_id: str) -> dict[str, Any]:
    services = inputs.ctx.services
    vehicle = await services.get("vehicle-master", f"/v1/vehicles/{vehicle_id}")
    if vehicle is None:
        raise not_found("vehicle", vehicle_id)
    if vehicle["fleetId"] != fleet_id:
        raise invalid("VEHICLE_NOT_IN_FLEET", f"vehicle {vehicle_id} is not in fleet {fleet_id}")
    sla = await services.get("fleet-master", f"/v1/fleets/{fleet_id}/sla")
    priority = await services.get("fleet-master", f"/v1/fleets/{fleet_id}/priority")
    if sla is None or priority is None:
        raise not_found("fleet", fleet_id)
    factors = [
        factor("sla_level", SLA_POINTS[sla["slaLevel"]],
               f"{sla['slaLevel']}, respond within {sla['responseTargetMinutes']} min"),
        factor("fleet_priority", PRIORITY_POINTS[priority["priorityLevel"]],
               priority["priorityLevel"]),
    ]
    twin = await inputs.twin(vehicle_id)
    if twin is not None:
        factors.append(factor("vehicle_health", HEALTH_POINTS[twin["healthState"]],
                              twin["healthState"]))
    total = sum(item["contribution"] for item in factors)
    return result(total, factors, inputs.confidence())


@HANDLERS.operation("calculateEventRisk")
async def calculate_event_risk(ctx: RequestContext) -> dict[str, Any]:
    inputs = Inputs(ctx)
    event = await inputs.event(ctx.path["event_id"])
    return {"eventId": event["eventId"], **await event_risk(inputs, event)}


@HANDLERS.operation("calculateSafetyRisk")
async def calculate_safety_risk(ctx: RequestContext) -> dict[str, Any]:
    inputs = Inputs(ctx)
    event = await inputs.event(ctx.path["event_id"])
    return {"eventId": event["eventId"], **await safety_risk(inputs, event)}


@HANDLERS.operation("calculateSlaRisk")
async def calculate_sla_risk(ctx: RequestContext) -> dict[str, Any]:
    vehicle_id, fleet_id = ctx.path["vehicle_id"], ctx.path["fleet_id"]
    return {
        "vehicleId": vehicle_id,
        "fleetId": fleet_id,
        **await sla_risk(Inputs(ctx), vehicle_id, fleet_id),
    }


@HANDLERS.operation("calculateCustomerImpact")
async def calculate_customer_impact(ctx: RequestContext) -> dict[str, Any]:
    inputs = Inputs(ctx)
    event = await inputs.event(ctx.path["event_id"])
    factors = [factor("severity", {"info": 0, "warning": 15, "critical": 30}[event["severity"]],
                      event["severity"])]
    vehicle = await inputs.vehicle(event["vehicleId"])
    fleet_id = vehicle["fleetId"] if vehicle else None
    fleet = None
    if fleet_id:
        fleet = await inputs.optional(ctx.services.get("fleet-master", f"/v1/fleets/{fleet_id}"))
    if fleet is not None:
        factors.append(factor("contract_tier", TIER_POINTS[fleet["contractTier"]],
                              fleet["contractTier"]))
        factors.append(factor("fleet_priority", PRIORITY_POINTS[fleet["priorityLevel"]],
                              fleet["priorityLevel"]))
    total = sum(item["contribution"] for item in factors)
    return {
        "eventId": event["eventId"],
        "affectedFleetIds": [fleet_id] if fleet_id else [],
        "affectedVehicleCount": 1,
        **result(total, factors, inputs.confidence()),
    }


@HANDLERS.operation("calculateCompositePriority")
async def calculate_composite_priority(ctx: RequestContext) -> dict[str, Any]:
    inputs = Inputs(ctx)
    event = await inputs.event(ctx.path["event_id"])
    components = {
        "event": await event_risk(inputs, event),
        "safety": await safety_risk(inputs, event),
    }
    vehicle = await inputs.vehicle(event["vehicleId"])
    if vehicle is not None and vehicle["fleetId"]:
        components["sla"] = await sla_risk(inputs, vehicle["vehicleId"], vehicle["fleetId"])
    weight = sum(COMPOSITE_WEIGHTS[name] for name in components)
    score = round(
        sum(COMPOSITE_WEIGHTS[name] * item["score"] for name, item in components.items()) / weight,
        1,
    )
    # Missing SLA context (no fleet) lowers confidence as well as removing that component.
    coverage = weight / sum(COMPOSITE_WEIGHTS.values())
    return {
        "eventId": event["eventId"],
        "priorityScore": score,
        "urgency": level(score),
        "confidence": round(inputs.confidence() * coverage, 2),
        "componentScores": {name: item["score"] for name, item in components.items()},
        "scoringPolicyVersion": POLICY_VERSION,
    }
