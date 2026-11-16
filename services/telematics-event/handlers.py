from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, Field
from psycopg.types.json import Jsonb

from fleetops_runtime import HandlerRegistry, RequestContext, RequestModel
from fleetops_runtime.db import fetch_all, fetch_one
from fleetops_runtime.errors import conflict, invalid, not_found
from fleetops_runtime.outbox import enqueue
from fleetops_runtime.util import content_hash, encode_cursor, iso, new_id, parse_time

HANDLERS = HandlerRegistry()

MAX_CLOCK_SKEW = timedelta(minutes=5)
SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}


def battery_severity(payload: dict[str, Any]) -> str:
    voltage = payload["voltage"]
    if voltage < 11.0:
        return "critical"
    if voltage < 11.8:
        return "warning"
    return "info"


def declared(default: str) -> Callable[[dict[str, Any]], str]:
    def classify(payload: dict[str, Any]) -> str:
        value = payload.get("severity", default)
        return value if value in SEVERITY_RANK else default

    return classify


def fixed(severity: str) -> Callable[[dict[str, Any]], str]:
    return lambda _: severity


@dataclass(frozen=True)
class EventRule:
    """How an event type is classified, whether it raises an alert, and what it clears."""

    severity: Callable[[dict[str, Any]], str]
    required: dict[str, type | tuple[type, ...]]
    raises_alert: bool = False
    clears: tuple[str, ...] = ()  # alert types cleared by an info-severity event


NUMBER = (int, float)
EVENT_RULES: dict[str, EventRule] = {
    "battery_voltage": EventRule(
        battery_severity, {"voltage": NUMBER}, raises_alert=True, clears=("battery_voltage",)
    ),
    "heartbeat": EventRule(
        fixed("info"), {}, clears=("heartbeat_missed", "connectivity_lost")
    ),
    "heartbeat_missed": EventRule(fixed("warning"), {}, raises_alert=True),
    "connectivity_lost": EventRule(fixed("warning"), {}, raises_alert=True),
    "connectivity_restored": EventRule(
        fixed("info"), {}, clears=("heartbeat_missed", "connectivity_lost")
    ),
    "diagnostic_failure": EventRule(declared("warning"), {"dtcCode": str}, raises_alert=True),
    "diagnostic_cleared": EventRule(fixed("info"), {}, clears=("diagnostic_failure",)),
    "location": EventRule(fixed("info"), {"latitude": NUMBER, "longitude": NUMBER}),
    "harsh_braking": EventRule(fixed("warning"), {}),
    "collision_detected": EventRule(fixed("critical"), {}, raises_alert=True),
    "firmware_update_failed": EventRule(
        fixed("warning"), {"firmwareVersion": str}, raises_alert=True
    ),
    "firmware_update_succeeded": EventRule(
        fixed("info"), {"firmwareVersion": str}, clears=("firmware_update_failed",)
    ),
    "ignition_on": EventRule(fixed("info"), {}),
    "ignition_off": EventRule(fixed("info"), {}),
}

EventId = Annotated[str, Field(pattern=r"^evt_[A-Za-z0-9_-]{1,60}$")]
OpaqueId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
RegionCode = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,31}$")]
EventType = Literal[tuple(EVENT_RULES)]  # type: ignore[valid-type]


def to_event(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "eventId": row["event_id"],
        "vehicleId": row["vehicle_id"],
        "eventType": row["event_type"],
        "severity": row["severity"],
        "regionCode": row["region_code"],
        "observedAt": iso(row["observed_at"]),
        "receivedAt": iso(row["received_at"]),
        "payload": row["payload"],
        "synthetic": row["synthetic"],
    }


class IngestEvent(RequestModel):
    eventId: EventId | None = Field(
        default=None,
        description="Device-assigned ID. A retry with the same ID and content is a duplicate; "
        "different content is a conflict. Generated when omitted.",
    )
    vehicleId: OpaqueId
    eventType: EventType
    observedAt: AwareDatetime
    payload: dict[str, Any] = Field(default_factory=dict)
    synthetic: bool = True
    regionCode: RegionCode | None = Field(
        default=None, description="Defaults to the vehicle's region in Vehicle Master."
    )


def validate_payload(event_type: str, payload: dict[str, Any]) -> None:
    for key, expected in EVENT_RULES[event_type].required.items():
        value = payload.get(key)
        if not isinstance(value, expected) or isinstance(value, bool):
            raise invalid(
                "INVALID_PAYLOAD", f"{event_type} payload needs {key}", field=f"payload.{key}"
            )


async def apply_alerts(ctx: RequestContext, event: dict[str, Any], rule: EventRule) -> None:
    severity, observed_at = event["severity"], event["observed_at"]
    if rule.raises_alert and severity != "info":
        active = await fetch_one(
            ctx.db,
            "SELECT * FROM telemetry.alerts WHERE vehicle_id = %s AND alert_type = %s "
            "AND status = 'active' FOR UPDATE",
            (event["vehicle_id"], event["event_type"]),
        )
        # A late event does not raise an alert that a newer reading already cleared.
        clearers = [name for name, other in EVENT_RULES.items()
                    if event["event_type"] in other.clears]
        superseded = await fetch_one(
            ctx.db,
            "SELECT 1 FROM telemetry.events WHERE vehicle_id = %s AND event_type = ANY(%s) "
            "AND severity = 'info' AND observed_at > %s LIMIT 1",
            (event["vehicle_id"], clearers, observed_at),
        )
        if superseded is not None:
            return
        if active is None:
            await ctx.db.execute(
                """
                INSERT INTO telemetry.alerts (
                    alert_id, vehicle_id, alert_type, severity, status, first_event_id,
                    last_event_id, raised_at, last_observed_at
                ) VALUES (%s, %s, %s, %s, 'active', %s, %s, %s, %s)
                """,
                (new_id("alert"), event["vehicle_id"], event["event_type"], severity,
                 event["event_id"], event["event_id"], observed_at, observed_at),
            )
        elif observed_at >= active["last_observed_at"]:
            worst = max(severity, active["severity"], key=SEVERITY_RANK.__getitem__)
            await ctx.db.execute(
                "UPDATE telemetry.alerts SET last_event_id = %s, last_observed_at = %s, "
                "severity = %s, updated_at = now() WHERE alert_id = %s",
                (event["event_id"], observed_at, worst, active["alert_id"]),
            )
    if severity == "info" and rule.clears:
        # An older event arriving late does not clear an alert raised after it.
        await ctx.db.execute(
            """
            UPDATE telemetry.alerts
            SET status = 'cleared', cleared_by_event_id = %s, cleared_at = %s, updated_at = now()
            WHERE vehicle_id = %s AND alert_type = ANY(%s) AND status = 'active'
              AND last_observed_at <= %s
            """,
            (event["event_id"], observed_at, event["vehicle_id"], list(rule.clears), observed_at),
        )


@HANDLERS.operation("ingestVehicleEvent", request=IngestEvent)
async def ingest(ctx: RequestContext) -> dict[str, Any]:
    body: IngestEvent = ctx.body
    if body.observedAt > datetime.now(UTC) + MAX_CLOCK_SKEW:
        raise invalid("EVENT_IN_FUTURE", "observedAt is more than 5 minutes in the future")
    validate_payload(body.eventType, body.payload)
    content = content_hash({
        "vehicleId": body.vehicleId,
        "eventType": body.eventType,
        "observedAt": iso(body.observedAt),
        "payload": body.payload,
        "synthetic": body.synthetic,
    })
    if body.eventId:
        existing = await fetch_one(
            ctx.db,
            "SELECT event_id, content_hash, received_at FROM telemetry.events WHERE event_id = %s",
            (body.eventId,),
        )
        if existing is not None:
            if existing["content_hash"] != content:
                raise conflict(
                    "EVENT_ID_CONFLICT", f"event {body.eventId} exists with different content"
                )
            return {
                "eventId": existing["event_id"],
                "status": "duplicate",
                "acceptedAt": iso(existing["received_at"]),
            }

    vehicle = await ctx.services.get("vehicle-master", f"/v1/vehicles/{body.vehicleId}")
    if vehicle is None:
        raise invalid("UNKNOWN_VEHICLE", f"vehicle {body.vehicleId} does not exist")

    rule = EVENT_RULES[body.eventType]
    event = await fetch_one(
        ctx.db,
        """
        INSERT INTO telemetry.events (
            event_id, vehicle_id, event_type, severity, region_code, observed_at,
            payload, synthetic, content_hash
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (
            body.eventId or new_id("evt"), body.vehicleId, body.eventType,
            rule.severity(body.payload), body.regionCode or vehicle["regionCode"],
            body.observedAt, Jsonb(body.payload), body.synthetic, content,
        ),
    )
    await apply_alerts(ctx, event, rule)
    await enqueue(ctx.db, "digital-twin-context", "/v1/digital-twins/events", {
        "eventId": event["event_id"],
        "vehicleId": event["vehicle_id"],
        "eventType": event["event_type"],
        "severity": event["severity"],
        "observedAt": iso(event["observed_at"]),
        "payload": event["payload"],
    })
    return {
        "eventId": event["event_id"],
        "status": "accepted",
        "acceptedAt": iso(event["received_at"]),
    }


async def search(ctx: RequestContext, column: str, value: str) -> dict[str, Any]:
    start = parse_time(ctx.query("from"), "from")
    end = parse_time(ctx.query("to"), "to")
    if start > end:
        raise invalid("INVALID_RANGE", "from must not be after to")
    after, limit = ctx.page(2)
    params: list[Any] = [value, start, end]
    page_filter = ""
    if after:
        page_filter = "AND (observed_at, event_id) < (%s, %s)"
        params += [parse_time(after[0], "cursor"), after[1]]
    rows = await fetch_all(
        ctx.db,
        f"""
        SELECT * FROM telemetry.events
        WHERE {column} = %s AND observed_at >= %s AND observed_at <= %s {page_filter}
        ORDER BY observed_at DESC, event_id DESC
        LIMIT %s
        """,
        (*params, limit + 1),
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [to_event(row) for row in rows],
        "nextCursor": (
            encode_cursor([iso(rows[-1]["observed_at"]), rows[-1]["event_id"]]) if more else ""
        ),
    }


@HANDLERS.operation("getRecentVehicleEvents")
async def vehicle_events(ctx: RequestContext) -> dict[str, Any]:
    return await search(ctx, "vehicle_id", ctx.path["vehicle_id"])


@HANDLERS.operation("searchEventsByType")
async def events_by_type(ctx: RequestContext) -> dict[str, Any]:
    return await search(ctx, "event_type", ctx.query("event_type"))


@HANDLERS.operation("searchEventsByRegion")
async def events_by_region(ctx: RequestContext) -> dict[str, Any]:
    return await search(ctx, "region_code", ctx.path["region"])


@HANDLERS.operation("getEventDetails")
async def event_details(ctx: RequestContext) -> dict[str, Any]:
    row = await fetch_one(
        ctx.db, "SELECT * FROM telemetry.events WHERE event_id = %s", (ctx.path["event_id"],)
    )
    if row is None:
        raise not_found("event", ctx.path["event_id"])
    return to_event(row)


@HANDLERS.operation("getActiveAlerts")
async def active_alerts(ctx: RequestContext) -> dict[str, Any]:
    rows = await fetch_all(
        ctx.db,
        "SELECT * FROM telemetry.alerts WHERE vehicle_id = %s AND status = 'active' "
        "ORDER BY raised_at, alert_id",
        (ctx.path["vehicle_id"],),
    )
    return {
        "vehicleId": ctx.path["vehicle_id"],
        "alerts": [
            {
                "alertId": row["alert_id"],
                "alertType": row["alert_type"],
                "eventId": row["last_event_id"],
                "firstEventId": row["first_event_id"],
                "severity": row["severity"],
                "status": row["status"],
                "raisedAt": iso(row["raised_at"]),
                "lastObservedAt": iso(row["last_observed_at"]),
            }
            for row in rows
        ],
    }
