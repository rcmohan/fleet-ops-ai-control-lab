"""Read-only composition over the authoritative services. Owns no data.

The vehicle itself must be reachable (404 if it does not exist, 503 if Vehicle Master is down).
Other sources are optional: when one is unavailable the bundle says so instead of failing.
"""

import asyncio
from typing import Any

from fleetops_runtime import HandlerRegistry, RequestContext
from fleetops_runtime.errors import DependencyUnavailable, invalid, not_found

HANDLERS = HandlerRegistry()

SECTIONS = ("profile", "fleet", "telematicsUnit", "operationalState")


async def vehicle(ctx: RequestContext) -> dict[str, Any]:
    vehicle_id = ctx.path["vehicle_id"]
    row = await ctx.services.get("vehicle-master", f"/v1/vehicles/{vehicle_id}")
    if row is None:
        raise not_found("vehicle", vehicle_id)
    return row


def profile_of(row: dict[str, Any]) -> dict[str, Any]:
    keys = ("vehicleId", "make", "model", "modelYear", "fleetId", "telematicsUnitId")
    return {key: row[key] for key in keys}


async def fleet_of(ctx: RequestContext, row: dict[str, Any]) -> dict[str, Any] | None:
    if not row["fleetId"]:
        return None
    return await ctx.services.get("fleet-master", f"/v1/fleets/{row['fleetId']}")


async def unit_of(ctx: RequestContext, row: dict[str, Any]) -> dict[str, Any] | None:
    if not row["telematicsUnitId"]:
        return None
    return await ctx.services.get(
        "telematics-unit-master", f"/v1/telematics-units/{row['telematicsUnitId']}"
    )


async def state_of(ctx: RequestContext, row: dict[str, Any]) -> dict[str, Any] | None:
    return await ctx.services.get(
        "digital-twin-context", f"/v1/digital-twins/vehicles/{row['vehicleId']}"
    )


@HANDLERS.operation("getVehicleProfile", nullable=("fleetId", "telematicsUnitId"))
async def get_profile(ctx: RequestContext) -> dict[str, Any]:
    return {**profile_of(await vehicle(ctx)), "source": "vehicle-master"}


@HANDLERS.operation("getVehicleTelematicsUnit", nullable=("unitId", "firmwareVersion"))
async def get_unit(ctx: RequestContext) -> dict[str, Any]:
    row = await vehicle(ctx)
    unit = await unit_of(ctx, row)
    return {
        "vehicleId": row["vehicleId"],
        "unitId": unit["unitId"] if unit else None,
        "firmwareVersion": unit["firmwareVersion"] if unit else None,
        "source": "telematics-unit-master",
    }


@HANDLERS.operation("getVehicleFleetAssignment", nullable=("fleetId", "customerName"))
async def get_fleet(ctx: RequestContext) -> dict[str, Any]:
    row = await vehicle(ctx)
    fleet = await fleet_of(ctx, row)
    return {
        "vehicleId": row["vehicleId"],
        "fleetId": row["fleetId"],
        "customerName": fleet["customerName"] if fleet else None,
        "source": "fleet-master",
    }


@HANDLERS.operation("getVehicleServiceHistory")
async def get_history(ctx: RequestContext) -> dict[str, Any]:
    row = await vehicle(ctx)
    try:
        page = await ctx.services.get(
            "maintenance-history", f"/v1/vehicles/{row['vehicleId']}/maintenance-records",
            cursor=ctx.query("cursor"), limit=ctx.query("limit"),
        )
    except DependencyUnavailable:
        return {"vehicleId": row["vehicleId"], "items": [], "nextCursor": "", "partial": True}
    return {
        "vehicleId": row["vehicleId"],
        "items": [
            {
                "maintenanceId": item["maintenanceId"],
                "status": item["serviceStatus"],
                "eventType": item["eventType"],
                "openedAt": item["openedAt"],
                "summary": item["summary"],
            }
            for item in page["items"]
        ],
        "nextCursor": page["nextCursor"],
        "partial": False,
    }


@HANDLERS.operation(
    "getVehicleCurrentState", nullable=("odometerKm", "observedAt")
)
async def get_state(ctx: RequestContext) -> dict[str, Any]:
    row = await vehicle(ctx)
    state = await state_of(ctx, row)
    return {
        "vehicleId": row["vehicleId"],
        "healthState": state["healthState"] if state else "unknown",
        "odometerKm": state["odometerKm"] if state else None,
        "observedAt": state["observedAt"] if state else None,
        "source": "digital-twin-context",
    }


@HANDLERS.operation(
    "getVehicleContext", nullable=("profile", "fleet", "telematicsUnit", "operationalState")
)
async def get_context(ctx: RequestContext) -> dict[str, Any]:
    raw = ctx.query("include")
    wanted = [part.strip() for part in raw.split(",") if part.strip()] if raw else list(SECTIONS)
    unknown = sorted(set(wanted) - set(SECTIONS))
    if unknown:
        raise invalid("UNKNOWN_SECTION", f"unknown include sections {unknown}; use {SECTIONS}")
    row = await vehicle(ctx)
    loaders = {
        "fleet": (fleet_of, "fleet-master"),
        "telematicsUnit": (unit_of, "telematics-unit-master"),
        "operationalState": (state_of, "digital-twin-context"),
    }
    names = [name for name in loaders if name in wanted]
    results = await asyncio.gather(
        *(loaders[name][0](ctx, row) for name in names), return_exceptions=True
    )
    bundle: dict[str, Any] = {
        "vehicleId": row["vehicleId"],
        "profile": profile_of(row) if "profile" in wanted else None,
        "fleet": None,
        "telematicsUnit": None,
        "operationalState": None,
        "unavailableDependencies": [],
    }
    for name, value in zip(names, results):
        if isinstance(value, DependencyUnavailable):
            bundle["unavailableDependencies"].append(loaders[name][1])
        elif isinstance(value, BaseException):
            raise value
        else:
            bundle[name] = value
    return bundle
