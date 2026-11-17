from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, Field
from psycopg.types.json import Jsonb

from fleetops_runtime import HandlerRegistry, RequestContext, RequestModel
from fleetops_runtime.db import fetch_all, fetch_one
from fleetops_runtime.errors import invalid, not_found
from fleetops_runtime.util import encode_cursor, iso

HANDLERS = HandlerRegistry()

SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}
HEALTH_BY_SEVERITY = {0: "healthy", 1: "warning", 2: "critical"}
RISK_BY_HEALTH = {"healthy": "low", "warning": "medium", "critical": "high"}

# event type -> issue it sets (non-info severity) and issues it clears.
ISSUE_SET = {
    "battery_voltage": "battery",
    "diagnostic_failure": "diagnostic",
    "collision_detected": "collision",  # stays until an inspection clears it; no event does yet
    "firmware_update_failed": "firmware",
}
ISSUE_CLEAR = {
    "battery_voltage": ("battery",),  # when severity is info
    "diagnostic_cleared": ("diagnostic",),
    "firmware_update_succeeded": ("firmware",),
}
CONNECTIVITY = {"heartbeat_missed": "degraded", "connectivity_lost": "disconnected"}

EventId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


def number(value: Any) -> float | None:
    return float(value) if value is not None else None


def to_state(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "vehicleId": row["vehicle_id"],
        "fleetId": row["fleet_id"],
        "healthState": row["health_state"],
        "connectivityState": row["connectivity_state"],
        "odometerKm": number(row["odometer_km"]),
        "batteryVoltage": number(row["battery_voltage"]),
        "lastLocation": row["last_location"],
        "activeIssues": [
            {"issue": name, **detail} for name, detail in sorted(row["issues"].items())
        ],
        "observedAt": iso(row["observed_at"]),
        "sourceVersion": row["state_version"],
    }


@HANDLERS.operation(
    "getVehicleOperationalState",
    nullable=("fleetId", "odometerKm", "batteryVoltage", "lastLocation"),
)
async def vehicle_state(ctx: RequestContext) -> dict[str, Any]:
    row = await fetch_one(
        ctx.db, "SELECT * FROM twin.vehicle_states WHERE vehicle_id = %s", (ctx.path["vehicle_id"],)
    )
    if row is None:
        raise not_found("vehicle state", ctx.path["vehicle_id"])
    return to_state(row)


HEALTH_STATES = ("healthy", "warning", "critical")
CONNECTIVITY_STATES = ("connected", "degraded", "disconnected")


@HANDLERS.operation("listVehicleOperationalStates")
async def list_states(ctx: RequestContext) -> dict[str, Any]:
    conditions, params = ["TRUE"], []
    for name, column, allowed in (
        ("fleet_id", "fleet_id", None),
        ("health_state", "health_state", HEALTH_STATES),
        ("connectivity_state", "connectivity_state", CONNECTIVITY_STATES),
    ):
        value = ctx.query(name)
        if value is None:
            continue
        if allowed is not None and value not in allowed:
            raise invalid(f"INVALID_{name.upper()}", f"{name} must be one of {list(allowed)}")
        conditions.append(f"{column} = %s")
        params.append(value)
    after, limit = ctx.page(1, default=200)
    if after:
        conditions.append("vehicle_id > %s")
        params.append(after[0])
    rows = await fetch_all(
        ctx.db,
        f"SELECT * FROM twin.vehicle_states WHERE {' AND '.join(conditions)} "
        "ORDER BY vehicle_id LIMIT %s",
        (*params, limit + 1),
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [to_state(row) for row in rows],
        "nextCursor": encode_cursor([rows[-1]["vehicle_id"]]) if more else "",
    }


@HANDLERS.operation("getFleetOperationalState", nullable=("observedAt",))
async def fleet_state(ctx: RequestContext) -> dict[str, Any]:
    row = await fetch_one(
        ctx.db,
        """
        SELECT count(*) AS total,
               count(*) FILTER (WHERE health_state = 'healthy') AS healthy,
               count(*) FILTER (WHERE health_state = 'warning') AS warning,
               count(*) FILTER (WHERE health_state = 'critical') AS critical,
               max(observed_at) AS observed_at
        FROM twin.vehicle_states WHERE fleet_id = %s
        """,
        (ctx.path["fleet_id"],),
    )
    return {
        "fleetId": ctx.path["fleet_id"],
        "vehicleCount": row["total"],
        "healthyVehicleCount": row["healthy"],
        "warningVehicleCount": row["warning"],
        "criticalVehicleCount": row["critical"],
        "observedAt": iso(row["observed_at"]),
    }


async def related(ctx: RequestContext, entity_id: str) -> list[dict[str, str]]:
    if entity_id.startswith("veh_"):
        vehicle = await ctx.services.get("vehicle-master", f"/v1/vehicles/{entity_id}")
        if vehicle is None:
            raise not_found("vehicle", entity_id)
        links = []
        if vehicle["fleetId"]:
            links.append({"entityId": vehicle["fleetId"], "entityType": "fleet",
                          "relationship": "member_of"})
        if vehicle["telematicsUnitId"]:
            links.append({"entityId": vehicle["telematicsUnitId"],
                          "entityType": "telematics_unit", "relationship": "equipped_with"})
        return links
    if entity_id.startswith("flt_"):
        fleet = await ctx.services.get("fleet-master", f"/v1/fleets/{entity_id}")
        if fleet is None:
            raise not_found("fleet", entity_id)
        members = await ctx.services.get(
            "vehicle-master", "/v1/vehicles", fleet_id=entity_id, limit=200
        )
        links = [
            {"entityId": item["vehicleId"], "entityType": "vehicle", "relationship": "member"}
            for item in (members or {"items": []})["items"]
        ]
        if fleet["preferredServiceProviderId"]:
            links.append({"entityId": fleet["preferredServiceProviderId"],
                          "entityType": "service_provider", "relationship": "preferred_provider"})
        return links
    raise invalid(
        "UNSUPPORTED_ENTITY", "relationships are available for vehicles (veh_) and fleets (flt_)"
    )


@HANDLERS.operation("getRelatedEntities")
async def related_entities(ctx: RequestContext) -> dict[str, Any]:
    entity_id = ctx.path["entity_id"]
    return {"entityId": entity_id, "relatedEntities": await related(ctx, entity_id)}


def entity_type(entity_id: str) -> str:
    return {"veh": "vehicle", "flt": "fleet", "tcu": "telematics_unit",
            "sp": "service_provider"}.get(entity_id.split("_", 1)[0], "unknown")


@HANDLERS.operation("getDependencyGraph")
async def dependency_graph(ctx: RequestContext) -> dict[str, Any]:
    """The root, its direct relationships, and the fleets' preferred providers (two hops)."""
    root = ctx.path["entity_id"]
    nodes = {root: entity_type(root)}
    edges: list[dict[str, str]] = []
    for link in await related(ctx, root):
        nodes[link["entityId"]] = link["entityType"]
        edges.append({"from": root, "to": link["entityId"], "relationship": link["relationship"]})
        if link["entityType"] == "fleet" and root.startswith("veh_"):
            fleet = await ctx.services.get("fleet-master", f"/v1/fleets/{link['entityId']}")
            provider = fleet and fleet["preferredServiceProviderId"]
            if provider:
                nodes[provider] = "service_provider"
                edges.append({"from": link["entityId"], "to": provider,
                              "relationship": "preferred_provider"})
    return {
        "rootEntityId": root,
        "nodes": [{"entityId": key, "entityType": value} for key, value in nodes.items()],
        "edges": edges,
    }


@HANDLERS.operation("getDownstreamImpact")
async def downstream_impact(ctx: RequestContext) -> dict[str, Any]:
    row = await fetch_one(
        ctx.db, "SELECT * FROM twin.applied_events WHERE event_id = %s", (ctx.path["event_id"],)
    )
    if row is None:
        raise not_found("applied event", ctx.path["event_id"])
    risk = RISK_BY_HEALTH[row["health_state_after"]]
    fleets = [row["fleet_id"]] if row["fleet_id"] else []
    summary = (
        f"{row['event_type']} ({row['severity']}) left vehicle {row['vehicle_id']} "
        f"{row['health_state_after']}"
        + (f"; fleet {row['fleet_id']} is affected" if fleets else "; no fleet assignment")
        + (" (event arrived after newer state and did not change it)"
           if row["outcome"] == "stale" else "")
    )
    return {
        "eventId": row["event_id"],
        "affectedVehicleIds": [row["vehicle_id"]],
        "affectedFleetIds": fleets,
        "riskLevel": risk,
        "summary": summary,
    }


class ApplyEvent(RequestModel):
    eventId: EventId
    vehicleId: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
    eventType: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,47}$")]
    severity: Literal["info", "warning", "critical"]
    observedAt: AwareDatetime
    payload: dict[str, Any] = Field(default_factory=dict)


def derive(state: dict[str, Any], event: ApplyEvent) -> dict[str, Any]:
    issues = dict(state["issues"])
    payload = event.payload
    detail = {"severity": event.severity, "since": iso(event.observedAt),
              "eventId": event.eventId}
    issue = ISSUE_SET.get(event.eventType)
    if issue and event.severity != "info":
        if issue in issues:
            detail["since"] = issues[issue]["since"]
        issues[issue] = detail
    if event.severity == "info":
        for name in ISSUE_CLEAR.get(event.eventType, ()):
            issues.pop(name, None)

    connectivity = CONNECTIVITY.get(event.eventType, "connected")
    if connectivity == "connected":
        issues.pop("connectivity", None)
    else:
        issues["connectivity"] = issues.get("connectivity", detail) | {"severity": "warning"}

    odometer = state["odometer_km"]
    if isinstance(payload.get("odometerKm"), (int, float)):
        odometer = max(float(payload["odometerKm"]), float(odometer or 0))
    battery = state["battery_voltage"]
    if event.eventType == "battery_voltage":
        battery = payload.get("voltage")
    location = state["last_location"]
    if event.eventType == "location":
        location = {key: payload[key] for key in ("latitude", "longitude", "speedKph")
                    if key in payload}

    worst = max((SEVERITY_RANK[item["severity"]] for item in issues.values()), default=0)
    return {
        "health_state": HEALTH_BY_SEVERITY[worst],
        "connectivity_state": connectivity,
        "odometer_km": odometer,
        "battery_voltage": battery,
        "last_location": Jsonb(location) if location is not None else None,
        "issues": Jsonb(issues),
        "observed_at": event.observedAt,
    }


@HANDLERS.operation("applyOperationalEvent", request=ApplyEvent)
async def apply_event(ctx: RequestContext) -> dict[str, Any]:
    event: ApplyEvent = ctx.body
    seen = await fetch_one(
        ctx.db, "SELECT state_version FROM twin.applied_events WHERE event_id = %s",
        (event.eventId,),
    )
    if seen is not None:
        return {"eventId": event.eventId, "stateVersion": seen["state_version"],
                "status": "duplicate"}

    vehicle = await ctx.services.get("vehicle-master", f"/v1/vehicles/{event.vehicleId}")
    if vehicle is None:
        raise invalid("UNKNOWN_VEHICLE", f"vehicle {event.vehicleId} does not exist")
    fleet_id = vehicle["fleetId"]

    await ctx.db.execute(
        """
        INSERT INTO twin.vehicle_states (
            vehicle_id, fleet_id, health_state, connectivity_state, observed_at, state_version
        ) VALUES (%s, %s, 'healthy', 'connected', %s, 0)
        ON CONFLICT (vehicle_id) DO NOTHING
        """,
        (event.vehicleId, fleet_id, event.observedAt),
    )
    state = await fetch_one(
        ctx.db, "SELECT * FROM twin.vehicle_states WHERE vehicle_id = %s FOR UPDATE",
        (event.vehicleId,),
    )
    stale = state["state_version"] > 0 and event.observedAt < state["observed_at"]
    if stale:
        await ctx.db.execute(
            "UPDATE twin.vehicle_states SET fleet_id = %s WHERE vehicle_id = %s",
            (fleet_id, event.vehicleId),
        )
        version, health = state["state_version"], state["health_state"]
    else:
        values = derive(state, event)
        updated = await fetch_one(
            ctx.db,
            """
            UPDATE twin.vehicle_states SET
                fleet_id = %s, health_state = %s, connectivity_state = %s, odometer_km = %s,
                battery_voltage = %s, last_location = %s, issues = %s, observed_at = %s,
                state_version = state_version + 1, updated_at = now()
            WHERE vehicle_id = %s
            RETURNING state_version, health_state
            """,
            (fleet_id, *values.values(), event.vehicleId),
        )
        version, health = updated["state_version"], updated["health_state"]

    await ctx.db.execute(
        """
        INSERT INTO twin.applied_events (
            event_id, vehicle_id, fleet_id, event_type, severity, observed_at, payload,
            outcome, state_version, health_state_after
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (event.eventId, event.vehicleId, fleet_id, event.eventType, event.severity,
         event.observedAt, Jsonb(event.payload), "stale" if stale else "applied",
         version, health),
    )
    return {"eventId": event.eventId, "stateVersion": version,
            "status": "stale" if stale else "applied"}
