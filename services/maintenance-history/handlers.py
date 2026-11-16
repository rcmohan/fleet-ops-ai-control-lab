from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, Field
from psycopg.types.json import Jsonb

from fleetops_runtime import HandlerRegistry, RequestContext, RequestModel
from fleetops_runtime.db import fetch_all, fetch_one, update_versioned
from fleetops_runtime.errors import invalid, not_found
from fleetops_runtime.util import encode_cursor, iso, new_id, parse_time

HANDLERS = HandlerRegistry()

MaintenanceId = Annotated[str, Field(pattern=r"^mtn_[a-z0-9_]{1,60}$")]
OpaqueId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
EventType = Literal["inspection", "preventive", "repair", "recall", "diagnostic", "other"]
Status = Literal["scheduled", "in_progress", "completed", "cancelled"]
Summary = Annotated[str, Field(min_length=1, max_length=2000)]
Odometer = Annotated[float, Field(ge=0)]

NULLABLE = ("serviceProviderId", "completedAt", "odometerKm", "resolution")

FIELDS = {
    "serviceProviderId": "service_provider_id",
    "eventType": "event_type",
    "serviceStatus": "service_status",
    "openedAt": "opened_at",
    "completedAt": "completed_at",
    "odometerKm": "odometer_km",
    "summary": "summary",
    "resolution": "resolution",
}


def to_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "maintenanceId": row["maintenance_id"],
        "vehicleId": row["vehicle_id"],
        "serviceProviderId": row["service_provider_id"],
        "eventType": row["event_type"],
        "serviceStatus": row["service_status"],
        "openedAt": iso(row["opened_at"]),
        "completedAt": iso(row["completed_at"]),
        "odometerKm": float(row["odometer_km"]) if row["odometer_km"] is not None else None,
        "summary": row["summary"],
        "resolution": row["resolution"],
        "sourceVersion": row["source_version"],
    }


def check_consistency(values: dict[str, Any]) -> None:
    opened, completed = values.get("opened_at"), values.get("completed_at")
    if completed is not None and opened is not None and completed < opened:
        raise invalid("COMPLETED_BEFORE_OPENED", "completedAt cannot be before openedAt")
    if values.get("service_status") == "completed" and completed is None:
        raise invalid("COMPLETION_TIME_REQUIRED", "a completed record needs completedAt")


@HANDLERS.operation("getMaintenanceRecord", nullable=NULLABLE)
async def get_record(ctx: RequestContext) -> dict[str, Any]:
    row = await fetch_one(
        ctx.db,
        "SELECT * FROM master_data.maintenance_records WHERE maintenance_id = %s",
        (ctx.path["maintenance_id"],),
    )
    if row is None:
        raise not_found("maintenance record", ctx.path["maintenance_id"])
    return to_record(row)


@HANDLERS.operation("getVehicleServiceHistory")
async def vehicle_history(ctx: RequestContext) -> dict[str, Any]:
    after, limit = ctx.page(2)
    params: list[Any] = [ctx.path["vehicle_id"]]
    page_filter = ""
    if after:
        page_filter = "AND (opened_at, maintenance_id) < (%s, %s)"
        params += [parse_time(after[0], "cursor"), after[1]]
    rows = await fetch_all(
        ctx.db,
        f"""
        SELECT * FROM master_data.maintenance_records
        WHERE vehicle_id = %s {page_filter}
        ORDER BY opened_at DESC, maintenance_id DESC
        LIMIT %s
        """,
        (*params, limit + 1),
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [to_record(row) for row in rows],
        "nextCursor": (
            encode_cursor([iso(rows[-1]["opened_at"]), rows[-1]["maintenance_id"]])
            if more else ""
        ),
    }


class RecordEvent(RequestModel):
    maintenanceId: MaintenanceId | None = Field(
        default=None, description="Optional caller-chosen ID for imports; generated when omitted."
    )
    vehicleId: OpaqueId
    serviceProviderId: OpaqueId | None = None
    eventType: EventType
    serviceStatus: Status
    openedAt: AwareDatetime
    completedAt: AwareDatetime | None = None
    odometerKm: Odometer | None = None
    summary: Summary
    resolution: Summary | None = None
    sourceReference: Annotated[str, Field(max_length=128)] | None = None


@HANDLERS.operation("recordMaintenanceEvent", request=RecordEvent, nullable=NULLABLE)
async def record_event(ctx: RequestContext) -> dict[str, Any]:
    body: RecordEvent = ctx.body
    values = {FIELDS[field]: value for field, value in body.model_dump().items() if field in FIELDS}
    check_consistency(values)
    if await ctx.services.get("vehicle-master", f"/v1/vehicles/{body.vehicleId}") is None:
        raise invalid("UNKNOWN_VEHICLE", f"vehicle {body.vehicleId} does not exist")
    if body.serviceProviderId:
        path = f"/v1/service-providers/{body.serviceProviderId}"
        if await ctx.services.get("service-provider-master", path) is None:
            raise invalid(
                "UNKNOWN_SERVICE_PROVIDER",
                f"service provider {body.serviceProviderId} does not exist",
            )
    maintenance_id = body.maintenanceId or new_id("mtn")
    row = await fetch_one(
        ctx.db,
        """
        INSERT INTO master_data.maintenance_records (
            maintenance_id, vehicle_id, service_provider_id, event_type, service_status,
            opened_at, completed_at, odometer_km, summary, resolution, source_reference
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (
            maintenance_id, body.vehicleId, body.serviceProviderId, body.eventType,
            body.serviceStatus, body.openedAt, body.completedAt, body.odometerKm,
            body.summary, body.resolution, body.sourceReference,
        ),
    )
    return to_record(row)


class CorrectionChanges(RequestModel):
    # Non-null types with a None default: omitted is fine, explicit null is rejected,
    # except where the column itself is nullable.
    serviceProviderId: OpaqueId | None = None
    eventType: EventType = None
    serviceStatus: Status = None
    openedAt: AwareDatetime = None
    completedAt: AwareDatetime | None = None
    odometerKm: Odometer | None = None
    summary: Summary = None
    resolution: Summary | None = None


class Correction(RequestModel):
    reason: Annotated[str, Field(min_length=1, max_length=1000)]
    changes: CorrectionChanges


@HANDLERS.operation("correctMaintenanceRecord", request=Correction, nullable=NULLABLE)
async def correct_record(ctx: RequestContext) -> dict[str, Any]:
    changes = ctx.body.changes.model_dump(exclude_unset=True)
    if not changes:
        raise invalid("EMPTY_CORRECTION", "changes must contain at least one field")
    current = await fetch_one(
        ctx.db,
        "SELECT * FROM master_data.maintenance_records WHERE maintenance_id = %s FOR UPDATE",
        (ctx.path["maintenance_id"],),
    )
    if current is None:
        raise not_found("maintenance record", ctx.path["maintenance_id"])
    columns = {FIELDS[field]: value for field, value in changes.items()}
    check_consistency({**current, **columns})
    row = await update_versioned(
        ctx.db, "master_data.maintenance_records", "maintenance_id",
        current["maintenance_id"], columns,
    )
    previous = {field: current[FIELDS[field]] for field in changes}
    await ctx.db.execute(
        """
        INSERT INTO master_data.maintenance_corrections (
            correction_id, maintenance_id, reason, changes, previous_values, resulting_version
        ) VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            new_id("corr"), current["maintenance_id"], ctx.body.reason,
            Jsonb(ctx.body.changes.model_dump(mode="json", exclude_unset=True)),
            Jsonb({key: iso(value) if isinstance(value, datetime) else
                   (float(value) if key == "odometerKm" and value is not None else value)
                   for key, value in previous.items()}),
            row["source_version"],
        ),
    )
    return to_record(row)
