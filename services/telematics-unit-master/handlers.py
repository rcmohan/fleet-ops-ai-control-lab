from datetime import date
from typing import Annotated, Any, Literal

from pydantic import Field

from fleetops_runtime import HandlerRegistry, RequestContext, RequestModel
from fleetops_runtime.db import fetch_all, fetch_one, touch_versioned, update_versioned
from fleetops_runtime.errors import conflict, not_found
from fleetops_runtime.util import iso, new_id

HANDLERS = HandlerRegistry()

UnitId = Annotated[str, Field(pattern=r"^tcu_[a-z0-9_]{1,60}$")]
Capability = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")]
Lifecycle = Literal["inventory", "active", "suspended", "decommissioned"]
Eligibility = Literal["eligible", "approval_required", "not_eligible"]
Firmware = Annotated[str, Field(pattern=r"^[0-9A-Za-z.+_-]{1,64}$")]

NULLABLE = ("activationDate", "networkCarrier")

ALLOWED_LIFECYCLE = {
    "inventory": {"active", "decommissioned"},
    "active": {"suspended", "decommissioned"},
    "suspended": {"active", "decommissioned"},
    "decommissioned": set(),
}


async def load(ctx: RequestContext, unit_id: str, *, lock: bool = False) -> dict[str, Any]:
    row = await fetch_one(
        ctx.db,
        "SELECT * FROM master_data.telematics_units WHERE unit_id = %s"
        + (" FOR UPDATE" if lock else ""),
        (unit_id,),
    )
    if row is None:
        raise not_found("telematics unit", unit_id)
    return row


async def to_unit(ctx: RequestContext, row: dict[str, Any]) -> dict[str, Any]:
    capabilities = await fetch_all(
        ctx.db,
        "SELECT capability_code FROM master_data.telematics_unit_capabilities "
        "WHERE unit_id = %s AND enabled ORDER BY capability_code",
        (row["unit_id"],),
    )
    return {
        "unitId": row["unit_id"],
        "serialNumber": row["serial_number"],
        "hardwareModel": row["hardware_model"],
        "firmwareVersion": row["firmware_version"],
        "activationDate": iso(row["activation_date"]),
        "networkCarrier": row["network_carrier"],
        "lifecycleStatus": row["lifecycle_status"],
        "remoteCommandEligibility": row["remote_command_eligibility"],
        "capabilities": [item["capability_code"] for item in capabilities],
        "sourceVersion": row["source_version"],
    }


async def replace_capabilities(ctx: RequestContext, unit_id: str, codes: list[str]) -> None:
    await ctx.db.execute(
        "DELETE FROM master_data.telematics_unit_capabilities WHERE unit_id = %s", (unit_id,)
    )
    for code in sorted(set(codes)):
        await ctx.db.execute(
            "INSERT INTO master_data.telematics_unit_capabilities (unit_id, capability_code) "
            "VALUES (%s, %s)",
            (unit_id, code),
        )


def not_decommissioned(row: dict[str, Any]) -> None:
    if row["lifecycle_status"] == "decommissioned":
        raise conflict("UNIT_DECOMMISSIONED", "a decommissioned unit cannot be changed")


@HANDLERS.operation("getTelematicsUnit", nullable=NULLABLE)
async def get_unit(ctx: RequestContext) -> dict[str, Any]:
    return await to_unit(ctx, await load(ctx, ctx.path["unit_id"]))


class CreateUnit(RequestModel):
    unitId: UnitId | None = Field(
        default=None, description="Optional caller-chosen ID for imports; generated when omitted."
    )
    serialNumber: Annotated[str, Field(min_length=1, max_length=96)]
    hardwareModel: Annotated[str, Field(min_length=1, max_length=80)]
    firmwareVersion: Firmware
    activationDate: date | None = None
    networkCarrier: Annotated[str, Field(max_length=80)] | None = None
    lifecycleStatus: Lifecycle = "inventory"
    remoteCommandEligibility: Eligibility = "not_eligible"
    capabilities: list[Capability] = Field(default_factory=list, max_length=32)


@HANDLERS.operation("createTelematicsUnit", request=CreateUnit, nullable=NULLABLE)
async def create_unit(ctx: RequestContext) -> dict[str, Any]:
    body: CreateUnit = ctx.body
    unit_id = body.unitId or new_id("tcu")
    row = await fetch_one(
        ctx.db,
        """
        INSERT INTO master_data.telematics_units (
            unit_id, serial_number, hardware_model, firmware_version, activation_date,
            network_carrier, lifecycle_status, remote_command_eligibility
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        RETURNING *
        """,
        (
            unit_id, body.serialNumber, body.hardwareModel, body.firmwareVersion,
            body.activationDate, body.networkCarrier, body.lifecycleStatus,
            body.remoteCommandEligibility,
        ),
    )
    if row is None:
        raise conflict("ALREADY_EXISTS", "unit ID or serial number already exists")
    await replace_capabilities(ctx, unit_id, body.capabilities)
    return await to_unit(ctx, row)


class FirmwareChange(RequestModel):
    firmwareVersion: Firmware


@HANDLERS.operation("updateFirmwareInventory", request=FirmwareChange, nullable=NULLABLE)
async def update_firmware(ctx: RequestContext) -> dict[str, Any]:
    unit = await load(ctx, ctx.path["unit_id"], lock=True)
    not_decommissioned(unit)
    if unit["firmware_version"] == ctx.body.firmwareVersion:
        return await to_unit(ctx, unit)
    row = await update_versioned(
        ctx.db, "master_data.telematics_units", "unit_id", unit["unit_id"],
        {"firmware_version": ctx.body.firmwareVersion},
    )
    return await to_unit(ctx, row)


class LifecycleChange(RequestModel):
    status: Lifecycle


@HANDLERS.operation(
    "setTelematicsUnitLifecycleStatus", request=LifecycleChange, nullable=NULLABLE
)
async def set_lifecycle(ctx: RequestContext) -> dict[str, Any]:
    unit = await load(ctx, ctx.path["unit_id"], lock=True)
    current, target = unit["lifecycle_status"], ctx.body.status
    if current == target:
        return await to_unit(ctx, unit)
    if target not in ALLOWED_LIFECYCLE[current]:
        raise conflict(
            "INVALID_TRANSITION", f"lifecycle cannot move from {current} to {target}",
            current=current,
        )
    values: dict[str, Any] = {"lifecycle_status": target}
    if target == "active" and unit["activation_date"] is None:
        values["activation_date"] = date.today()
    if target in {"suspended", "decommissioned"}:
        values["remote_command_eligibility"] = "not_eligible"
    row = await update_versioned(
        ctx.db, "master_data.telematics_units", "unit_id", unit["unit_id"], values
    )
    return await to_unit(ctx, row)


class EligibilityChange(RequestModel):
    eligibility: Eligibility


@HANDLERS.operation("setRemoteCommandEligibility", request=EligibilityChange, nullable=NULLABLE)
async def set_eligibility(ctx: RequestContext) -> dict[str, Any]:
    unit = await load(ctx, ctx.path["unit_id"], lock=True)
    not_decommissioned(unit)
    target = ctx.body.eligibility
    if target != "not_eligible" and unit["lifecycle_status"] != "active":
        raise conflict(
            "UNIT_NOT_ACTIVE", "only an active unit can be made eligible for remote commands"
        )
    if unit["remote_command_eligibility"] == target:
        return await to_unit(ctx, unit)
    row = await update_versioned(
        ctx.db, "master_data.telematics_units", "unit_id", unit["unit_id"],
        {"remote_command_eligibility": target},
    )
    return await to_unit(ctx, row)


class CapabilitiesChange(RequestModel):
    capabilities: list[Capability] = Field(max_length=32)


@HANDLERS.operation("replaceTelematicsUnitCapabilities", request=CapabilitiesChange)
async def set_capabilities(ctx: RequestContext) -> dict[str, Any]:
    unit = await load(ctx, ctx.path["unit_id"], lock=True)
    not_decommissioned(unit)
    await replace_capabilities(ctx, unit["unit_id"], ctx.body.capabilities)
    row = await touch_versioned(ctx.db, "master_data.telematics_units", "unit_id", unit["unit_id"])
    result = await to_unit(ctx, row)
    return {
        "unitId": result["unitId"],
        "capabilities": result["capabilities"],
        "sourceVersion": result["sourceVersion"],
    }
