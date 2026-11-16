from typing import Annotated, Any, Literal

from pydantic import Field

from fleetops_runtime import HandlerRegistry, RequestContext, RequestModel
from fleetops_runtime.db import fetch_all, fetch_one, touch_versioned, update_versioned
from fleetops_runtime.errors import conflict, invalid, not_found
from fleetops_runtime.util import encode_cursor, new_id

HANDLERS = HandlerRegistry()

ProviderId = Annotated[str, Field(pattern=r"^sp_[a-z0-9_]{1,61}$")]
RegionCode = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,31}$")]
Capability = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")]
Lifecycle = Literal["active", "at_capacity", "suspended", "closed"]
Name = Annotated[str, Field(min_length=1, max_length=160)]
NonNegative = Annotated[int, Field(ge=0)]

NULLABLE = ("averageResponseMinutes", "dailyCapacity")

ALLOWED_STATUS = {
    "active": {"at_capacity", "suspended", "closed"},
    "at_capacity": {"active", "suspended", "closed"},
    "suspended": {"active", "closed"},
    "closed": set(),
}


async def load(ctx: RequestContext, provider_id: str, *, lock: bool = False) -> dict[str, Any]:
    row = await fetch_one(
        ctx.db,
        "SELECT * FROM master_data.service_providers WHERE provider_id = %s"
        + (" FOR UPDATE" if lock else ""),
        (provider_id,),
    )
    if row is None:
        raise not_found("service provider", provider_id)
    return row


async def coverage_of(ctx: RequestContext, provider_id: str) -> tuple[list[str], list[str]]:
    regions = await fetch_all(
        ctx.db,
        "SELECT region_code FROM master_data.service_provider_regions "
        "WHERE provider_id = %s ORDER BY region_code",
        (provider_id,),
    )
    capabilities = await fetch_all(
        ctx.db,
        "SELECT capability_code FROM master_data.service_provider_capabilities "
        "WHERE provider_id = %s AND active ORDER BY capability_code",
        (provider_id,),
    )
    return (
        [row["region_code"] for row in regions],
        [row["capability_code"] for row in capabilities],
    )


async def to_provider(ctx: RequestContext, row: dict[str, Any]) -> dict[str, Any]:
    regions, capabilities = await coverage_of(ctx, row["provider_id"])
    return {
        "providerId": row["provider_id"],
        "providerName": row["provider_name"],
        "lifecycleStatus": row["lifecycle_status"],
        "averageResponseMinutes": row["average_response_minutes"],
        "dailyCapacity": row["daily_capacity"],
        "regions": regions,
        "capabilities": capabilities,
        "sourceVersion": row["source_version"],
    }


async def replace_coverage(
    ctx: RequestContext, provider_id: str, regions: list[str], capabilities: list[str]
) -> None:
    await ctx.db.execute(
        "DELETE FROM master_data.service_provider_regions WHERE provider_id = %s", (provider_id,)
    )
    await ctx.db.execute(
        "DELETE FROM master_data.service_provider_capabilities WHERE provider_id = %s",
        (provider_id,),
    )
    for region in sorted(set(regions)):
        await ctx.db.execute(
            "INSERT INTO master_data.service_provider_regions (provider_id, region_code) "
            "VALUES (%s, %s)",
            (provider_id, region),
        )
    for capability in sorted(set(capabilities)):
        await ctx.db.execute(
            "INSERT INTO master_data.service_provider_capabilities (provider_id, capability_code) "
            "VALUES (%s, %s)",
            (provider_id, capability),
        )


def not_closed(row: dict[str, Any]) -> None:
    if row["lifecycle_status"] == "closed":
        raise conflict("PROVIDER_CLOSED", "a closed provider cannot be changed")


@HANDLERS.operation("getServiceProvider", nullable=NULLABLE)
async def get_provider(ctx: RequestContext) -> dict[str, Any]:
    return await to_provider(ctx, await load(ctx, ctx.path["provider_id"]))


@HANDLERS.operation("listServiceProviders")
async def list_providers(ctx: RequestContext) -> dict[str, Any]:
    after, limit = ctx.page(1)
    conditions, params = [], []
    if ctx.query("region"):
        conditions.append(
            "EXISTS (SELECT 1 FROM master_data.service_provider_regions r "
            "WHERE r.provider_id = p.provider_id AND r.region_code = %s)"
        )
        params.append(ctx.query("region"))
    if ctx.query("capability"):
        conditions.append(
            "EXISTS (SELECT 1 FROM master_data.service_provider_capabilities c "
            "WHERE c.provider_id = p.provider_id AND c.active AND c.capability_code = %s)"
        )
        params.append(ctx.query("capability"))
    if after:
        conditions.append("p.provider_id > %s")
        params.append(after[0])
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = await fetch_all(
        ctx.db,
        f"SELECT p.* FROM master_data.service_providers p {where} "
        "ORDER BY p.provider_id LIMIT %s",
        (*params, limit + 1),
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [await to_provider(ctx, row) for row in rows],
        "nextCursor": encode_cursor([rows[-1]["provider_id"]]) if more else "",
    }


class CreateProvider(RequestModel):
    providerId: ProviderId | None = Field(
        default=None, description="Optional caller-chosen ID for imports; generated when omitted."
    )
    providerName: Name
    lifecycleStatus: Lifecycle = "active"
    averageResponseMinutes: NonNegative | None = None
    dailyCapacity: NonNegative | None = None
    regions: list[RegionCode] = Field(default_factory=list, max_length=32)
    capabilities: list[Capability] = Field(default_factory=list, max_length=32)


@HANDLERS.operation("createServiceProvider", request=CreateProvider, nullable=NULLABLE)
async def create_provider(ctx: RequestContext) -> dict[str, Any]:
    body: CreateProvider = ctx.body
    provider_id = body.providerId or new_id("sp")
    row = await fetch_one(
        ctx.db,
        """
        INSERT INTO master_data.service_providers (
            provider_id, provider_name, lifecycle_status, average_response_minutes, daily_capacity
        ) VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        RETURNING *
        """,
        (provider_id, body.providerName, body.lifecycleStatus, body.averageResponseMinutes,
         body.dailyCapacity),
    )
    if row is None:
        raise conflict("ALREADY_EXISTS", f"service provider {provider_id} already exists")
    await replace_coverage(ctx, provider_id, body.regions, body.capabilities)
    return await to_provider(ctx, row)


class UpdateProvider(RequestModel):
    providerName: Name = None  # non-null type: explicit null is rejected
    averageResponseMinutes: NonNegative | None = None
    dailyCapacity: NonNegative | None = None


@HANDLERS.operation("updateServiceProvider", request=UpdateProvider, nullable=NULLABLE)
async def update_provider(ctx: RequestContext) -> dict[str, Any]:
    changes = ctx.body.model_dump(exclude_unset=True)
    if not changes:
        raise invalid("EMPTY_UPDATE", "provide at least one field to change")
    provider = await load(ctx, ctx.path["provider_id"], lock=True)
    not_closed(provider)
    columns = {
        "providerName": "provider_name",
        "averageResponseMinutes": "average_response_minutes",
        "dailyCapacity": "daily_capacity",
    }
    row = await update_versioned(
        ctx.db, "master_data.service_providers", "provider_id", provider["provider_id"],
        {columns[field]: value for field, value in changes.items()},
    )
    return await to_provider(ctx, row)


class StatusChange(RequestModel):
    status: Lifecycle


@HANDLERS.operation("setServiceProviderStatus", request=StatusChange, nullable=NULLABLE)
async def set_status(ctx: RequestContext) -> dict[str, Any]:
    provider = await load(ctx, ctx.path["provider_id"], lock=True)
    current, target = provider["lifecycle_status"], ctx.body.status
    if current == target:
        return await to_provider(ctx, provider)
    if target not in ALLOWED_STATUS[current]:
        raise conflict(
            "INVALID_TRANSITION", f"status cannot move from {current} to {target}",
            current=current,
        )
    row = await update_versioned(
        ctx.db, "master_data.service_providers", "provider_id", provider["provider_id"],
        {"lifecycle_status": target},
    )
    return await to_provider(ctx, row)


class CoverageChange(RequestModel):
    regions: list[RegionCode] = Field(max_length=32)
    capabilities: list[Capability] = Field(max_length=32)


@HANDLERS.operation("replaceServiceProviderCoverage", request=CoverageChange)
async def set_coverage(ctx: RequestContext) -> dict[str, Any]:
    provider = await load(ctx, ctx.path["provider_id"], lock=True)
    not_closed(provider)
    await replace_coverage(ctx, provider["provider_id"], ctx.body.regions, ctx.body.capabilities)
    row = await touch_versioned(
        ctx.db, "master_data.service_providers", "provider_id", provider["provider_id"]
    )
    regions, capabilities = await coverage_of(ctx, row["provider_id"])
    return {
        "providerId": row["provider_id"],
        "regions": regions,
        "capabilities": capabilities,
        "sourceVersion": row["source_version"],
    }
