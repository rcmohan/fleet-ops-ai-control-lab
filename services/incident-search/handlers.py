from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, Field, model_validator

from fleetops_runtime import HandlerRegistry, RequestContext, RequestModel
from fleetops_runtime.db import fetch_all, fetch_one
from fleetops_runtime.errors import conflict, not_found
from fleetops_runtime.util import content_hash, encode_cursor, iso

HANDLERS = HandlerRegistry()

# Similarity = 0.5 for the same event type + 0.3 x symptom overlap (Jaccard) + 0.2 same region.
SIMILARITY_SQL = """
    (CASE WHEN event_type = %(event_type)s THEN 0.5 ELSE 0 END)
    + 0.3 * COALESCE(
        cardinality(ARRAY(SELECT unnest(symptoms) INTERSECT SELECT unnest(%(symptoms)s::text[])))::float
        / NULLIF(cardinality(ARRAY(SELECT unnest(symptoms) UNION SELECT unnest(%(symptoms)s::text[]))), 0),
        0)
    + (CASE WHEN %(region)s::text IS NOT NULL AND region_code = %(region)s THEN 0.2 ELSE 0 END)
"""

Symptom = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")]
EventType = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,47}$")]
RegionCode = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,31}$")]
OpaqueId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


class SearchIncidents(RequestModel):
    eventType: EventType
    symptoms: list[Symptom] = Field(default_factory=list, max_length=20)
    regionCode: RegionCode | None = None


@HANDLERS.operation("searchSimilarIncidents", request=SearchIncidents)
async def search_similar(ctx: RequestContext) -> dict[str, Any]:
    body: SearchIncidents = ctx.body
    after, limit = ctx.page(1, default=10)
    offset = int(after[0]) if after else 0
    rows = await fetch_all(
        ctx.db,
        f"""
        SELECT * FROM (
            SELECT incident_id, event_type, symptoms, region_code, outcome, resolution,
                   round(({SIMILARITY_SQL})::numeric, 3)::float AS similarity
            FROM incidents.resolved_incidents
        ) scored
        WHERE similarity > 0
        ORDER BY similarity DESC, incident_id
        OFFSET %(offset)s LIMIT %(limit)s
        """,
        {
            "event_type": body.eventType, "symptoms": body.symptoms, "region": body.regionCode,
            "offset": offset, "limit": limit + 1,
        },
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [
            {
                "incidentId": row["incident_id"],
                "similarity": row["similarity"],
                "eventType": row["event_type"],
                "symptoms": row["symptoms"],
                "regionCode": row["region_code"],
                "outcome": row["outcome"],
                "resolution": row["resolution"],
            }
            for row in rows
        ],
        "nextCursor": encode_cursor([offset + limit]) if more else "",
    }


@HANDLERS.operation("getIncidentResolution", nullable=("rootCause",))
async def incident_resolution(ctx: RequestContext) -> dict[str, Any]:
    row = await fetch_one(
        ctx.db, "SELECT * FROM incidents.resolved_incidents WHERE incident_id = %s",
        (ctx.path["incident_id"],),
    )
    if row is None:
        raise not_found("incident", ctx.path["incident_id"])
    return {
        "incidentId": row["incident_id"],
        "rootCause": row["root_cause"],
        "resolution": row["resolution"],
        "outcome": row["outcome"],
        "timeToResolveMinutes": row["time_to_resolve_minutes"],
    }


@HANDLERS.operation("getCommonResolutionPatterns")
async def resolution_patterns(ctx: RequestContext) -> dict[str, Any]:
    rows = await fetch_all(
        ctx.db,
        """
        SELECT resolution, count(*) AS occurrences,
               round(avg((outcome = 'resolved')::int)::numeric, 3)::float AS success_rate
        FROM incidents.resolved_incidents
        WHERE event_type = %s
        GROUP BY resolution
        ORDER BY occurrences DESC, resolution
        LIMIT 20
        """,
        (ctx.query("event_type"),),
    )
    return {
        "eventType": ctx.query("event_type"),
        "patterns": [
            {
                "resolution": row["resolution"],
                "occurrences": row["occurrences"],
                "successRate": row["success_rate"],
            }
            for row in rows
        ],
    }


@HANDLERS.operation(
    "getHistoricalResolutionTime", nullable=("medianMinutes", "p95Minutes")
)
async def resolution_time(ctx: RequestContext) -> dict[str, Any]:
    row = await fetch_one(
        ctx.db,
        """
        SELECT count(*) AS sample_size,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY time_to_resolve_minutes) AS median,
               percentile_cont(0.95) WITHIN GROUP (ORDER BY time_to_resolve_minutes) AS p95
        FROM incidents.resolved_incidents
        WHERE event_type = %s AND outcome = 'resolved'
        """,
        (ctx.query("event_type"),),
    )
    return {
        "eventType": ctx.query("event_type"),
        "sampleSize": row["sample_size"],
        "medianMinutes": round(row["median"]) if row["median"] is not None else None,
        "p95Minutes": round(row["p95"]) if row["p95"] is not None else None,
    }


class IndexIncident(RequestModel):
    incidentId: Annotated[str, Field(pattern=r"^inc_[A-Za-z0-9_-]{1,60}$")]
    sourceCaseId: OpaqueId | None = None
    vehicleId: OpaqueId
    eventType: EventType
    symptoms: list[Symptom] = Field(default_factory=list, max_length=20)
    regionCode: RegionCode | None = None
    rootCause: Annotated[str, Field(max_length=2000)] | None = None
    resolution: Annotated[str, Field(min_length=1, max_length=2000)]
    outcome: Literal["resolved", "workaround", "unresolved"]
    openedAt: AwareDatetime
    resolvedAt: AwareDatetime

    @model_validator(mode="after")
    def resolved_after_opened(self) -> "IndexIncident":
        if self.resolvedAt < self.openedAt:
            raise ValueError("resolvedAt cannot be before openedAt")
        return self


@HANDLERS.operation("indexResolvedIncident", request=IndexIncident)
async def index_incident(ctx: RequestContext) -> dict[str, Any]:
    """Idempotent: the same incident with the same content is accepted again unchanged."""
    body: IndexIncident = ctx.body
    digest = content_hash(body.model_dump(mode="json"))
    row = await fetch_one(
        ctx.db,
        """
        INSERT INTO incidents.resolved_incidents (
            incident_id, source_case_id, vehicle_id, event_type, symptoms, region_code,
            root_cause, resolution, outcome, opened_at, resolved_at, content_hash
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        RETURNING incident_id, indexed_at
        """,
        (
            body.incidentId, body.sourceCaseId, body.vehicleId, body.eventType,
            sorted(set(body.symptoms)), body.regionCode, body.rootCause, body.resolution,
            body.outcome, body.openedAt, body.resolvedAt, digest,
        ),
    )
    if row is not None:
        return {"incidentId": row["incident_id"], "status": "indexed",
                "indexedAt": iso(row["indexed_at"])}
    existing = await fetch_one(
        ctx.db,
        "SELECT incident_id, content_hash, indexed_at FROM incidents.resolved_incidents "
        "WHERE incident_id = %s",
        (body.incidentId,),
    )
    if existing is None or existing["content_hash"] != digest:
        raise conflict("INCIDENT_CONFLICT", f"incident {body.incidentId} has different content")
    return {"incidentId": existing["incident_id"], "status": "duplicate",
            "indexedAt": iso(existing["indexed_at"])}
