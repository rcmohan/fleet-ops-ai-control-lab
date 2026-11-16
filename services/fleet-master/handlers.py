from datetime import date
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from fleetops_runtime import HandlerRegistry, RequestContext, RequestModel
from fleetops_runtime.db import fetch_all, fetch_one, touch_versioned, update_versioned
from fleetops_runtime.errors import conflict, invalid, not_found
from fleetops_runtime.util import encode_cursor, iso, new_id

HANDLERS = HandlerRegistry()

FleetId = Annotated[str, Field(pattern=r"^flt_[a-z0-9_]{1,60}$")]
OpaqueId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
RegionCode = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,31}$")]
Tier = Literal["basic", "standard", "premium", "enterprise"]
SlaLevel = Literal["standard", "enhanced", "mission_critical"]
Priority = Literal["low", "standard", "high", "critical"]
Lifecycle = Literal["prospect", "active", "suspended", "closed"]
Name = Annotated[str, Field(min_length=1, max_length=160)]
Industry = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")]

FIELDS = {
    "customerName": "customer_name",
    "industryCode": "industry_code",
    "declaredFleetSize": "declared_fleet_size",
    "contractTier": "contract_tier",
    "slaLevel": "sla_level",
    "priorityLevel": "priority_level",
    "preferredServiceProviderId": "preferred_service_provider_id",
    "lifecycleStatus": "lifecycle_status",
    "contractEffectiveDate": "contract_effective_date",
}


async def load(ctx: RequestContext, fleet_id: str, *, lock: bool = False) -> dict[str, Any]:
    row = await fetch_one(
        ctx.db,
        "SELECT * FROM master_data.fleets WHERE fleet_id = %s" + (" FOR UPDATE" if lock else ""),
        (fleet_id,),
    )
    if row is None:
        raise not_found("fleet", fleet_id)
    return row


async def regions_of(ctx: RequestContext, fleet_id: str) -> list[str]:
    rows = await fetch_all(
        ctx.db,
        "SELECT region_code FROM master_data.fleet_operating_regions "
        "WHERE fleet_id = %s ORDER BY region_code",
        (fleet_id,),
    )
    return [row["region_code"] for row in rows]


async def to_fleet(ctx: RequestContext, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "fleetId": row["fleet_id"],
        "customerName": row["customer_name"],
        "industryCode": row["industry_code"],
        "declaredFleetSize": row["declared_fleet_size"],
        "contractTier": row["contract_tier"],
        "slaLevel": row["sla_level"],
        "priorityLevel": row["priority_level"],
        "preferredServiceProviderId": row["preferred_service_provider_id"],
        "lifecycleStatus": row["lifecycle_status"],
        "operatingRegions": await regions_of(ctx, row["fleet_id"]),
        "sourceVersion": row["source_version"],
    }


async def require_provider(ctx: RequestContext, provider_id: str) -> None:
    path = f"/v1/service-providers/{provider_id}"
    if await ctx.services.get("service-provider-master", path) is None:
        raise invalid(
            "UNKNOWN_SERVICE_PROVIDER", f"service provider {provider_id} does not exist",
            providerId=provider_id,
        )


async def replace_regions(ctx: RequestContext, fleet_id: str, regions: list[str]) -> None:
    await ctx.db.execute(
        "DELETE FROM master_data.fleet_operating_regions WHERE fleet_id = %s", (fleet_id,)
    )
    for region in sorted(set(regions)):
        await ctx.db.execute(
            "INSERT INTO master_data.fleet_operating_regions (fleet_id, region_code) "
            "VALUES (%s, %s)",
            (fleet_id, region),
        )


def not_closed(row: dict[str, Any]) -> None:
    if row["lifecycle_status"] == "closed":
        raise conflict("FLEET_CLOSED", "a closed fleet cannot be changed")


PROFILE_NULLABLE = ("preferredServiceProviderId",)


@HANDLERS.operation("getFleetProfile", nullable=PROFILE_NULLABLE)
async def get_fleet(ctx: RequestContext) -> dict[str, Any]:
    return await to_fleet(ctx, await load(ctx, ctx.path["fleet_id"]))


@HANDLERS.operation("getFleetContract")
async def get_contract(ctx: RequestContext) -> dict[str, Any]:
    row = await load(ctx, ctx.path["fleet_id"])
    return {
        "fleetId": row["fleet_id"],
        "contractTier": row["contract_tier"],
        "effectiveDate": iso(row["contract_effective_date"]),
    }


@HANDLERS.operation("getFleetSla")
async def get_sla(ctx: RequestContext) -> dict[str, Any]:
    row = await fetch_one(
        ctx.db,
        "SELECT f.fleet_id, f.sla_level, s.response_target_minutes "
        "FROM master_data.fleets f JOIN master_data.sla_levels s USING (sla_level) "
        "WHERE f.fleet_id = %s",
        (ctx.path["fleet_id"],),
    )
    if row is None:
        raise not_found("fleet", ctx.path["fleet_id"])
    return {
        "fleetId": row["fleet_id"],
        "slaLevel": row["sla_level"],
        "responseTargetMinutes": row["response_target_minutes"],
    }


@HANDLERS.operation("getFleetPriorityLevel")
async def get_priority(ctx: RequestContext) -> dict[str, Any]:
    row = await load(ctx, ctx.path["fleet_id"])
    return {"fleetId": row["fleet_id"], "priorityLevel": row["priority_level"]}


@HANDLERS.operation("listFleets")
async def list_fleets(ctx: RequestContext) -> dict[str, Any]:
    after, limit = ctx.page(1)
    conditions, params = [], []
    if ctx.query("region"):
        conditions.append(
            "EXISTS (SELECT 1 FROM master_data.fleet_operating_regions r "
            "WHERE r.fleet_id = f.fleet_id AND r.region_code = %s)"
        )
        params.append(ctx.query("region"))
    if ctx.query("lifecycle_status"):
        conditions.append("f.lifecycle_status = %s")
        params.append(ctx.query("lifecycle_status"))
    if after:
        conditions.append("f.fleet_id > %s")
        params.append(after[0])
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = await fetch_all(
        ctx.db,
        f"SELECT f.* FROM master_data.fleets f {where} ORDER BY f.fleet_id LIMIT %s",
        (*params, limit + 1),
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [await to_fleet(ctx, row) for row in rows],
        "nextCursor": encode_cursor([rows[-1]["fleet_id"]]) if more else "",
    }


class CreateFleet(RequestModel):
    fleetId: FleetId | None = Field(
        default=None, description="Optional caller-chosen ID for imports; generated when omitted."
    )
    customerName: Name
    industryCode: Industry
    contractTier: Tier
    slaLevel: SlaLevel
    declaredFleetSize: Annotated[int, Field(ge=0)] = 0
    priorityLevel: Priority = "standard"
    preferredServiceProviderId: OpaqueId | None = None
    lifecycleStatus: Lifecycle = "active"
    contractEffectiveDate: date | None = None
    operatingRegions: list[RegionCode] = Field(default_factory=list, max_length=32)


@HANDLERS.operation("createFleet", request=CreateFleet, nullable=PROFILE_NULLABLE)
async def create_fleet(ctx: RequestContext) -> dict[str, Any]:
    body: CreateFleet = ctx.body
    fleet_id = body.fleetId or new_id("flt")
    if body.preferredServiceProviderId:
        await require_provider(ctx, body.preferredServiceProviderId)
    values = body.model_dump(exclude={"fleetId", "operatingRegions"}, exclude_none=True)
    columns = ", ".join(["fleet_id", *(FIELDS[field] for field in values)])
    placeholders = ", ".join(["%s"] * (len(values) + 1))
    row = await fetch_one(
        ctx.db,
        f"INSERT INTO master_data.fleets ({columns}) VALUES ({placeholders}) "
        "ON CONFLICT DO NOTHING RETURNING *",
        (fleet_id, *values.values()),
    )
    if row is None:
        raise conflict("ALREADY_EXISTS", f"fleet {fleet_id} already exists")
    await replace_regions(ctx, fleet_id, body.operatingRegions)
    return await to_fleet(ctx, row)


class UpdateFleet(RequestModel):
    # Non-null types with a None default: omitted is fine, explicit null is rejected.
    customerName: Name = None
    industryCode: Industry = None
    declaredFleetSize: Annotated[int, Field(ge=0)] = None
    contractTier: Tier = None
    slaLevel: SlaLevel = None
    priorityLevel: Priority = None
    lifecycleStatus: Lifecycle = None
    contractEffectiveDate: date = None
    preferredServiceProviderId: OpaqueId | None = Field(
        default=None, description="null clears the preferred provider"
    )


@HANDLERS.operation("updateFleet", request=UpdateFleet, nullable=PROFILE_NULLABLE)
async def update_fleet(ctx: RequestContext) -> dict[str, Any]:
    changes = ctx.body.model_dump(exclude_unset=True)
    if not changes:
        raise invalid("EMPTY_UPDATE", "provide at least one field to change")
    fleet = await load(ctx, ctx.path["fleet_id"], lock=True)
    not_closed(fleet)
    if changes.get("preferredServiceProviderId"):
        await require_provider(ctx, changes["preferredServiceProviderId"])
    row = await update_versioned(
        ctx.db, "master_data.fleets", "fleet_id", fleet["fleet_id"],
        {FIELDS[field]: value for field, value in changes.items()},
    )
    return await to_fleet(ctx, row)


class RegionsChange(RequestModel):
    regions: list[RegionCode] = Field(max_length=32)


@HANDLERS.operation("replaceFleetOperatingRegions", request=RegionsChange)
async def set_regions(ctx: RequestContext) -> dict[str, Any]:
    fleet = await load(ctx, ctx.path["fleet_id"], lock=True)
    not_closed(fleet)
    await replace_regions(ctx, fleet["fleet_id"], ctx.body.regions)
    row = await touch_versioned(ctx.db, "master_data.fleets", "fleet_id", fleet["fleet_id"])
    return {
        "fleetId": row["fleet_id"],
        "regions": await regions_of(ctx, row["fleet_id"]),
        "sourceVersion": row["source_version"],
    }


class Contact(RequestModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    role: Annotated[str, Field(min_length=1, max_length=80)]
    email: Annotated[str, Field(pattern=r"^[^@\s]+@[^@\s]+$", max_length=254)] | None = None
    phone: Annotated[str, Field(pattern=r"^\+?[0-9 ()-]{5,40}$")] | None = None
    escalationRank: Annotated[int, Field(ge=1, le=99)] | None = None

    @model_validator(mode="after")
    def needs_a_contact_method(self) -> "Contact":
        if self.email is None and self.phone is None:
            raise ValueError("a contact needs an email or a phone number")
        return self


class ContactsChange(RequestModel):
    contacts: list[Contact] = Field(max_length=20)


@HANDLERS.operation("replaceFleetEscalationContacts", request=ContactsChange)
async def set_contacts(ctx: RequestContext) -> dict[str, Any]:
    fleet = await load(ctx, ctx.path["fleet_id"], lock=True)
    not_closed(fleet)
    await ctx.db.execute(
        "DELETE FROM master_data.fleet_escalation_contacts WHERE fleet_id = %s",
        (fleet["fleet_id"],),
    )
    contacts = []
    for position, contact in enumerate(ctx.body.contacts, start=1):
        contact_id = new_id("contact")
        rank = contact.escalationRank or position
        await ctx.db.execute(
            """
            INSERT INTO master_data.fleet_escalation_contacts (
                contact_id, fleet_id, contact_name, contact_role, email_address,
                phone_number, escalation_rank
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (contact_id, fleet["fleet_id"], contact.name, contact.role, contact.email,
             contact.phone, rank),
        )
        contacts.append({
            "contactId": contact_id, "name": contact.name, "role": contact.role,
            "email": contact.email, "phone": contact.phone, "escalationRank": rank,
        })
    row = await touch_versioned(ctx.db, "master_data.fleets", "fleet_id", fleet["fleet_id"])
    return {
        "fleetId": row["fleet_id"],
        "contacts": sorted(contacts, key=lambda item: item["escalationRank"]),
        "sourceVersion": row["source_version"],
    }
