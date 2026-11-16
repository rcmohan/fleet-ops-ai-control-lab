"""Notification drafts and simulated delivery. Nothing is sent outside the lab."""

from typing import Annotated, Any

from pydantic import Field

from fleetops_runtime import HandlerRegistry, RequestContext, RequestModel
from fleetops_runtime.db import fetch_one
from fleetops_runtime.errors import conflict, forbidden, invalid, not_found
from fleetops_runtime.util import iso, new_id

HANDLERS = HandlerRegistry()

OpaqueId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
TeamId = Annotated[str, Field(pattern=r"^team_[a-z0-9_]{1,59}$")]
Message = Annotated[str, Field(min_length=1, max_length=4000)]
FLEET_MANAGER_ACTION = "fleet_notification"


async def insert(ctx: RequestContext, **values: Any) -> dict[str, Any]:
    columns = ", ".join(["notification_id", *values])
    placeholders = ", ".join(["%s"] * (len(values) + 1))
    return await fetch_one(
        ctx.db,
        f"INSERT INTO notifications.notifications ({columns}) VALUES ({placeholders}) RETURNING *",
        (new_id("ntf"), *values.values()),
    )


async def deliver(ctx: RequestContext, notification_id: str) -> dict[str, Any]:
    """Simulated delivery: record one successful attempt."""
    await ctx.db.execute(
        "INSERT INTO notifications.delivery_attempts (notification_id, outcome, detail) "
        "VALUES (%s, 'delivered', 'synthetic channel')",
        (notification_id,),
    )
    return await fetch_one(
        ctx.db,
        """
        UPDATE notifications.notifications
        SET status = 'delivered', attempt_count = attempt_count + 1,
            delivered_at = now(), updated_at = now()
        WHERE notification_id = %s
        RETURNING *
        """,
        (notification_id,),
    )


class FleetDraft(RequestModel):
    fleetId: OpaqueId
    eventId: OpaqueId
    message: Message | None = Field(
        default=None, description="Optional text; a summary of the event is drafted when omitted."
    )


@HANDLERS.operation("draftFleetNotification", request=FleetDraft)
async def draft_fleet(ctx: RequestContext) -> dict[str, Any]:
    body: FleetDraft = ctx.body
    fleet = await ctx.services.get("fleet-master", f"/v1/fleets/{body.fleetId}")
    if fleet is None:
        raise invalid("UNKNOWN_FLEET", f"fleet {body.fleetId} does not exist")
    event = await ctx.services.get("telematics-event", f"/v1/events/{body.eventId}")
    if event is None:
        raise invalid("UNKNOWN_EVENT", f"event {body.eventId} does not exist")
    message = body.message or (
        f"{fleet['customerName']}: vehicle {event['vehicleId']} reported "
        f"{event['eventType'].replace('_', ' ')} ({event['severity']}) at {event['observedAt']}. "
        "Our operations team is reviewing it."
    )
    row = await insert(
        ctx, kind="fleet_draft", channel="email", status="draft",
        fleet_id=body.fleetId, event_id=body.eventId, message=message,
    )
    return {
        "notificationId": row["notification_id"],
        "fleetId": row["fleet_id"],
        "eventId": row["event_id"],
        "channel": row["channel"],
        "status": row["status"],
        "message": row["message"],
    }


class InternalNotification(RequestModel):
    teamId: TeamId
    message: Message


@HANDLERS.operation("sendInternalNotification", request=InternalNotification)
async def send_internal(ctx: RequestContext) -> dict[str, Any]:
    row = await insert(
        ctx, kind="internal", channel="internal", status="draft",
        team_id=ctx.body.teamId, message=ctx.body.message,
    )
    row = await deliver(ctx, row["notification_id"])
    return {
        "notificationId": row["notification_id"],
        "status": row["status"],
        "channel": row["channel"],
        "deliveredAt": iso(row["delivered_at"]),
    }


class FleetManagerNotification(RequestModel):
    fleetId: OpaqueId
    message: Message
    approvalId: OpaqueId


@HANDLERS.operation("sendFleetManagerNotification", request=FleetManagerNotification)
async def send_fleet_manager(ctx: RequestContext) -> dict[str, Any]:
    body: FleetManagerNotification = ctx.body
    used = await fetch_one(
        ctx.db, "SELECT notification_id FROM notifications.notifications WHERE approval_id = %s",
        (body.approvalId,),
    )
    if used is not None:
        raise conflict(
            "APPROVAL_ALREADY_USED", f"approval {body.approvalId} already sent a message",
            notificationId=used["notification_id"],
        )
    approval = await ctx.services.get("approval", f"/v1/approvals/{body.approvalId}")
    if approval is None:
        raise forbidden("APPROVAL_NOT_FOUND", f"approval {body.approvalId} does not exist")
    if approval["actionType"] != FLEET_MANAGER_ACTION:
        raise forbidden(
            "APPROVAL_WRONG_ACTION",
            f"approval {body.approvalId} is for {approval['actionType']}, not {FLEET_MANAGER_ACTION}",
        )
    if approval["status"] != "approved":
        raise forbidden(
            "APPROVAL_NOT_GRANTED", f"approval {body.approvalId} is {approval['status']}",
            approvalStatus=approval["status"],
        )
    if await ctx.services.get("fleet-master", f"/v1/fleets/{body.fleetId}") is None:
        raise invalid("UNKNOWN_FLEET", f"fleet {body.fleetId} does not exist")
    row = await insert(
        ctx, kind="fleet_manager", channel="email", status="draft",
        fleet_id=body.fleetId, approval_id=body.approvalId, message=body.message,
    )
    row = await deliver(ctx, row["notification_id"])
    return {
        "notificationId": row["notification_id"],
        "status": row["status"],
        "channel": row["channel"],
        "approvalId": row["approval_id"],
        "deliveredAt": iso(row["delivered_at"]),
    }


@HANDLERS.operation("getNotificationStatus")
async def notification_status(ctx: RequestContext) -> dict[str, Any]:
    row = await fetch_one(
        ctx.db, "SELECT * FROM notifications.notifications WHERE notification_id = %s",
        (ctx.path["notification_id"],),
    )
    if row is None:
        raise not_found("notification", ctx.path["notification_id"])
    return {
        "notificationId": row["notification_id"],
        "status": row["status"],
        "channel": row["channel"],
        "attemptCount": row["attempt_count"],
        "updatedAt": iso(row["updated_at"]),
    }
