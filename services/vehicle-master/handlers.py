from typing import Annotated, Any, Literal

from pydantic import Field

from fleetops_runtime import HandlerRegistry, RequestContext, RequestModel
from fleetops_runtime.db import fetch_all, fetch_one, update_versioned
from fleetops_runtime.errors import conflict, invalid, not_found
from fleetops_runtime.util import encode_cursor, new_id

HANDLERS = HandlerRegistry()

VehicleId = Annotated[str, Field(pattern=r"^veh_[a-z0-9_]{1,60}$")]
OpaqueId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
RegionCode = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,31}$")]
Powertrain = Literal[
    "gasoline", "diesel", "hybrid", "plug_in_hybrid", "battery_electric", "hydrogen", "other"
]
Lifecycle = Literal["ordered", "active", "inactive", "retired"]
ServiceStatus = Literal["in_service", "maintenance", "out_of_service", "retired"]
Warranty = Literal["active", "expired", "unknown"]
Priority = Literal["low", "standard", "high", "critical"]
Text80 = Annotated[str, Field(min_length=1, max_length=80)]
ModelYear = Annotated[int, Field(ge=1980, le=2200)]

FIELDS = {
    "syntheticVin": "synthetic_vin",
    "make": "make",
    "model": "model",
    "modelYear": "model_year",
    "powertrainType": "powertrain_type",
    "regionCode": "region_code",
    "lifecycleStatus": "lifecycle_status",
    "serviceStatus": "service_status",
    "warrantyStatus": "warranty_status",
    "priorityLevel": "priority_level",
    "fleetId": "fleet_id",
    "telematicsUnitId": "telematics_unit_id",
}


def to_vehicle(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "vehicleId": row["vehicle_id"],
        **{field: row[column] for field, column in FIELDS.items()},
        "sourceVersion": row["source_version"],
    }


async def load(ctx: RequestContext, vehicle_id: str, *, lock: bool = False) -> dict[str, Any]:
    row = await fetch_one(
        ctx.db,
        "SELECT * FROM master_data.vehicles WHERE vehicle_id = %s" + (" FOR UPDATE" if lock else ""),
        (vehicle_id,),
    )
    if row is None:
        raise not_found("vehicle", vehicle_id)
    return row


async def require_fleet(ctx: RequestContext, fleet_id: str) -> None:
    if await ctx.services.get("fleet-master", f"/v1/fleets/{fleet_id}") is None:
        raise invalid("UNKNOWN_FLEET", f"fleet {fleet_id} does not exist", fleetId=fleet_id)


async def require_unit(ctx: RequestContext, unit_id: str) -> None:
    unit = await ctx.services.get("telematics-unit-master", f"/v1/telematics-units/{unit_id}")
    if unit is None:
        raise invalid("UNKNOWN_TELEMATICS_UNIT", f"unit {unit_id} does not exist", unitId=unit_id)
    if unit["lifecycleStatus"] == "decommissioned":
        raise conflict("TELEMATICS_UNIT_DECOMMISSIONED", f"unit {unit_id} is decommissioned")


async def require_unit_free(ctx: RequestContext, unit_id: str, vehicle_id: str | None) -> None:
    holder = await fetch_one(
        ctx.db,
        "SELECT vehicle_id FROM master_data.vehicles WHERE telematics_unit_id = %s",
        (unit_id,),
    )
    if holder is not None and holder["vehicle_id"] != vehicle_id:
        raise conflict(
            "TELEMATICS_UNIT_ASSIGNED",
            f"unit {unit_id} is assigned to {holder['vehicle_id']}",
            vehicleId=holder["vehicle_id"],
        )


NULLABLE = ("fleetId", "telematicsUnitId")


@HANDLERS.operation("getVehicleProfile", nullable=NULLABLE)
async def get_vehicle(ctx: RequestContext) -> dict[str, Any]:
    return to_vehicle(await load(ctx, ctx.path["vehicle_id"]))


class CreateVehicle(RequestModel):
    vehicleId: VehicleId | None = Field(
        default=None, description="Optional caller-chosen ID for imports; generated when omitted."
    )
    syntheticVin: Annotated[str, Field(pattern=r"^[A-Z0-9]{11,17}$")]
    make: Text80
    model: Text80
    modelYear: ModelYear
    powertrainType: Powertrain
    regionCode: RegionCode
    lifecycleStatus: Lifecycle = "active"
    serviceStatus: ServiceStatus = "in_service"
    warrantyStatus: Warranty = "unknown"
    priorityLevel: Priority = "standard"
    fleetId: OpaqueId | None = None
    telematicsUnitId: OpaqueId | None = None


@HANDLERS.operation("createVehicle", request=CreateVehicle, nullable=NULLABLE)
async def create_vehicle(ctx: RequestContext) -> dict[str, Any]:
    body: CreateVehicle = ctx.body
    vehicle_id = body.vehicleId or new_id("veh")
    if body.fleetId:
        await require_fleet(ctx, body.fleetId)
    if body.telematicsUnitId:
        await require_unit(ctx, body.telematicsUnitId)
        # A repeat of an import holds the unit itself; that surfaces as ALREADY_EXISTS below.
        await require_unit_free(ctx, body.telematicsUnitId, body.vehicleId)
    values = body.model_dump(exclude={"vehicleId"})
    columns = ", ".join(["vehicle_id", *(FIELDS[field] for field in values)])
    placeholders = ", ".join(["%s"] * (len(values) + 1))
    row = await fetch_one(
        ctx.db,
        f"INSERT INTO master_data.vehicles ({columns}) VALUES ({placeholders}) "
        "ON CONFLICT DO NOTHING RETURNING *",
        (vehicle_id, *values.values()),
    )
    if row is None:
        raise conflict("ALREADY_EXISTS", "vehicle ID or synthetic VIN already exists")
    return to_vehicle(row)


class UpdateVehicle(RequestModel):
    # Fields default to None but are typed non-null, so an explicit null is rejected.
    make: Text80 = None
    model: Text80 = None
    modelYear: ModelYear = None
    powertrainType: Powertrain = None
    regionCode: RegionCode = None
    serviceStatus: ServiceStatus = None
    warrantyStatus: Warranty = None
    priorityLevel: Priority = None


@HANDLERS.operation("updateVehicleProfile", request=UpdateVehicle, nullable=NULLABLE)
async def update_vehicle(ctx: RequestContext) -> dict[str, Any]:
    changes = ctx.body.model_dump(exclude_unset=True)
    if not changes:
        raise invalid("EMPTY_UPDATE", "provide at least one field to change")
    vehicle = await load(ctx, ctx.path["vehicle_id"], lock=True)
    if vehicle["lifecycle_status"] == "retired":
        raise conflict("VEHICLE_RETIRED", "a retired vehicle cannot be changed")
    row = await update_versioned(
        ctx.db,
        "master_data.vehicles",
        "vehicle_id",
        vehicle["vehicle_id"],
        {FIELDS[field]: value for field, value in changes.items()},
    )
    return to_vehicle(row)


class LifecycleChange(RequestModel):
    status: Lifecycle


ALLOWED_LIFECYCLE = {
    "ordered": {"active", "retired"},
    "active": {"inactive", "retired"},
    "inactive": {"active", "retired"},
    "retired": set(),
}


@HANDLERS.operation("setVehicleLifecycleStatus", request=LifecycleChange, nullable=NULLABLE)
async def set_lifecycle(ctx: RequestContext) -> dict[str, Any]:
    target = ctx.body.status
    vehicle = await load(ctx, ctx.path["vehicle_id"], lock=True)
    current = vehicle["lifecycle_status"]
    if target == current:
        return to_vehicle(vehicle)
    if target not in ALLOWED_LIFECYCLE[current]:
        raise conflict(
            "INVALID_TRANSITION", f"lifecycle cannot move from {current} to {target}",
            current=current,
        )
    values: dict[str, Any] = {"lifecycle_status": target}
    if target == "retired":
        values.update(service_status="retired", telematics_unit_id=None)
    row = await update_versioned(
        ctx.db, "master_data.vehicles", "vehicle_id", vehicle["vehicle_id"], values
    )
    return to_vehicle(row)


class FleetAssignment(RequestModel):
    fleetId: OpaqueId | None = Field(description="null removes the assignment")


@HANDLERS.operation("assignVehicleToFleet", request=FleetAssignment, nullable=("fleetId",))
async def assign_fleet(ctx: RequestContext) -> dict[str, Any]:
    fleet_id = ctx.body.fleetId
    vehicle = await load(ctx, ctx.path["vehicle_id"], lock=True)
    if vehicle["lifecycle_status"] == "retired":
        raise conflict("VEHICLE_RETIRED", "a retired vehicle cannot be assigned")
    if fleet_id == vehicle["fleet_id"]:
        row = vehicle
    else:
        if fleet_id:
            await require_fleet(ctx, fleet_id)
        row = await update_versioned(
            ctx.db, "master_data.vehicles", "vehicle_id", vehicle["vehicle_id"],
            {"fleet_id": fleet_id},
        )
    return {
        "vehicleId": row["vehicle_id"],
        "fleetId": row["fleet_id"],
        "sourceVersion": row["source_version"],
    }


class UnitAssignment(RequestModel):
    telematicsUnitId: OpaqueId | None = Field(description="null removes the assignment")


@HANDLERS.operation(
    "assignTelematicsUnit", request=UnitAssignment, nullable=("telematicsUnitId",)
)
async def assign_unit(ctx: RequestContext) -> dict[str, Any]:
    unit_id = ctx.body.telematicsUnitId
    vehicle = await load(ctx, ctx.path["vehicle_id"], lock=True)
    if vehicle["lifecycle_status"] == "retired":
        raise conflict("VEHICLE_RETIRED", "a retired vehicle cannot be assigned")
    if unit_id == vehicle["telematics_unit_id"]:
        row = vehicle
    else:
        if unit_id:
            await require_unit(ctx, unit_id)
            await require_unit_free(ctx, unit_id, vehicle["vehicle_id"])
        row = await update_versioned(
            ctx.db, "master_data.vehicles", "vehicle_id", vehicle["vehicle_id"],
            {"telematics_unit_id": unit_id},
        )
    return {
        "vehicleId": row["vehicle_id"],
        "telematicsUnitId": row["telematics_unit_id"],
        "sourceVersion": row["source_version"],
    }


@HANDLERS.operation("listVehiclesByFleet")
async def list_vehicles(ctx: RequestContext) -> dict[str, Any]:
    after, limit = ctx.page(1)
    conditions, params = [], []
    if ctx.query("fleet_id"):
        conditions.append("fleet_id = %s")
        params.append(ctx.query("fleet_id"))
    if after:
        conditions.append("vehicle_id > %s")
        params.append(after[0])
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = await fetch_all(
        ctx.db,
        f"SELECT * FROM master_data.vehicles {where} ORDER BY vehicle_id LIMIT %s",
        (*params, limit + 1),
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [to_vehicle(row) for row in rows],
        "nextCursor": encode_cursor([rows[-1]["vehicle_id"]]) if more else "",
    }
