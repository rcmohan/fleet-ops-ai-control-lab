from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import Field

from fleetops_runtime import HandlerRegistry, RequestContext, RequestModel
from fleetops_runtime.db import fetch_one, update_versioned
from fleetops_runtime.errors import conflict, invalid, not_found
from fleetops_runtime.outbox import enqueue
from fleetops_runtime.util import iso, new_id

HANDLERS = HandlerRegistry()

OpaqueId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
TeamId = Annotated[str, Field(pattern=r"^team_[a-z0-9_]{1,59}$")]
Symptom = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")]
Text = Annotated[str, Field(min_length=1, max_length=4000)]
Status = Literal["open", "in_progress", "resolved", "closed", "cancelled"]

TRANSITIONS = {
    "open": {"in_progress", "resolved", "cancelled"},
    "in_progress": {"open", "resolved", "cancelled"},
    "resolved": {"in_progress", "closed"},
    "closed": set(),
    "cancelled": set(),
}
TERMINAL = {"closed", "cancelled"}
NULLABLE = ("recommendationId", "assignedTeamId", "auditTraceId", "eventType", "resolution")


def workflow_state(row: dict[str, Any]) -> str:
    if row["status"] in {"open", "in_progress"}:
        return "assigned" if row["assigned_team_id"] else "triage"
    return row["status"]


def to_case(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "caseId": row["case_id"],
        "vehicleId": row["vehicle_id"],
        "recommendationId": row["recommendation_id"],
        "summary": row["summary"],
        "eventType": row["event_type"],
        "status": row["status"],
        "assignedTeamId": row["assigned_team_id"],
        "workflowState": workflow_state(row),
        "auditTraceId": row["audit_trace_id"],
        "resolution": row["resolution"],
        "createdAt": iso(row["created_at"]),
        "sourceVersion": row["source_version"],
    }


async def load(ctx: RequestContext, case_id: str, *, lock: bool = False) -> dict[str, Any]:
    row = await fetch_one(
        ctx.db,
        "SELECT * FROM cases.service_cases WHERE case_id = %s" + (" FOR UPDATE" if lock else ""),
        (case_id,),
    )
    if row is None:
        raise not_found("case", case_id)
    return row


async def history(
    ctx: RequestContext, case_id: str, change: str, old: Any, new: Any, comment: str | None = None
) -> None:
    await ctx.db.execute(
        "INSERT INTO cases.case_history (case_id, change_type, from_value, to_value, comment) "
        "VALUES (%s, %s, %s, %s, %s)",
        (case_id, change, old, new, comment),
    )


class CreateCase(RequestModel):
    vehicleId: OpaqueId
    summary: Text
    recommendationId: OpaqueId | None = None
    eventType: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,47}$")] | None = None
    symptoms: list[Symptom] = Field(default_factory=list, max_length=20)
    regionCode: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,31}$")] | None = None
    assignedTeamId: TeamId | None = None
    traceId: OpaqueId | None = None


@HANDLERS.operation("createServiceCase", request=CreateCase, nullable=NULLABLE)
async def create_case(ctx: RequestContext) -> dict[str, Any]:
    body: CreateCase = ctx.body
    if body.recommendationId:
        existing = await fetch_one(
            ctx.db, "SELECT case_id FROM cases.service_cases WHERE recommendation_id = %s",
            (body.recommendationId,),
        )
        if existing is not None:
            raise conflict(
                "CASE_EXISTS_FOR_RECOMMENDATION",
                f"recommendation {body.recommendationId} already has a case",
                caseId=existing["case_id"],
            )
    vehicle = await ctx.services.get("vehicle-master", f"/v1/vehicles/{body.vehicleId}")
    if vehicle is None:
        raise invalid("UNKNOWN_VEHICLE", f"vehicle {body.vehicleId} does not exist")
    row = await fetch_one(
        ctx.db,
        """
        INSERT INTO cases.service_cases (
            case_id, vehicle_id, recommendation_id, summary, event_type, symptoms, region_code,
            status, assigned_team_id, audit_trace_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'open', %s, %s)
        RETURNING *
        """,
        (
            new_id("case"), body.vehicleId, body.recommendationId, body.summary, body.eventType,
            sorted(set(body.symptoms)), body.regionCode or vehicle["regionCode"],
            body.assignedTeamId, body.traceId,
        ),
    )
    await history(ctx, row["case_id"], "created", None, "open")
    return to_case(row)


class StatusChange(RequestModel):
    status: Status
    comment: Annotated[str, Field(max_length=2000)] | None = None
    resolution: Text | None = Field(default=None, description="Required when resolving.")
    rootCause: Text | None = None
    outcome: Literal["resolved", "workaround", "unresolved"] = "resolved"


@HANDLERS.operation("updateCase", request=StatusChange, nullable=NULLABLE)
async def update_status(ctx: RequestContext) -> dict[str, Any]:
    body: StatusChange = ctx.body
    case = await load(ctx, ctx.path["case_id"], lock=True)
    current = case["status"]
    if body.status == current:
        return to_case(case)
    if body.status not in TRANSITIONS[current]:
        raise conflict(
            "INVALID_TRANSITION", f"case cannot move from {current} to {body.status}",
            current=current,
        )
    values: dict[str, Any] = {"status": body.status}
    if body.status == "in_progress" and not case["assigned_team_id"]:
        raise conflict("CASE_NOT_ASSIGNED", "assign the case to a team before starting work")
    if body.status == "resolved":
        if not body.resolution:
            raise invalid("RESOLUTION_REQUIRED", "a resolution is required to resolve a case")
        values.update(
            resolution=body.resolution, root_cause=body.rootCause,
            resolution_outcome=body.outcome, resolved_at=datetime.now(UTC),
        )
    row = await update_versioned(ctx.db, "cases.service_cases", "case_id", case["case_id"], values)
    if body.status == "resolved" and row["event_type"]:
        # Resolved cases become searchable history. The incident ID carries the case version,
        # so a case that is reopened and resolved again is indexed as a separate incident.
        await enqueue(ctx.db, "incident-search", "/v1/incidents", {
            "incidentId": f"inc_{row['case_id']}_v{row['source_version']}",
            "sourceCaseId": row["case_id"],
            "vehicleId": row["vehicle_id"],
            "eventType": row["event_type"],
            "symptoms": row["symptoms"],
            "regionCode": row["region_code"],
            "rootCause": row["root_cause"],
            "resolution": row["resolution"],
            "outcome": row["resolution_outcome"],
            "openedAt": iso(row["created_at"]),
            "resolvedAt": iso(row["resolved_at"]),
        })
    await history(ctx, case["case_id"], "status", current, body.status, body.comment)
    return to_case(row)


class Assignment(RequestModel):
    teamId: TeamId


@HANDLERS.operation("assignCase", request=Assignment, nullable=NULLABLE)
async def assign(ctx: RequestContext) -> dict[str, Any]:
    case = await load(ctx, ctx.path["case_id"], lock=True)
    if case["status"] in TERMINAL or case["status"] == "resolved":
        raise conflict("CASE_NOT_ACTIVE", f"a {case['status']} case cannot be reassigned")
    if case["assigned_team_id"] == ctx.body.teamId:
        return to_case(case)
    row = await update_versioned(
        ctx.db, "cases.service_cases", "case_id", case["case_id"],
        {"assigned_team_id": ctx.body.teamId},
    )
    await history(ctx, case["case_id"], "assignment", case["assigned_team_id"], ctx.body.teamId)
    return to_case(row)


class AgentSummary(RequestModel):
    recommendationId: OpaqueId | None = None
    summary: Text
    traceId: OpaqueId | None = None


@HANDLERS.operation("attachAgentSummary", request=AgentSummary)
async def attach_summary(ctx: RequestContext) -> dict[str, Any]:
    case = await load(ctx, ctx.path["case_id"], lock=True)
    if case["status"] in TERMINAL:
        raise conflict("CASE_NOT_ACTIVE", f"a {case['status']} case cannot take attachments")
    row = await fetch_one(
        ctx.db,
        """
        INSERT INTO cases.case_attachments (
            attachment_id, case_id, attachment_type, recommendation_id, summary, trace_id
        ) VALUES (%s, %s, 'agent_summary', %s, %s, %s)
        RETURNING *
        """,
        (new_id("attachment"), case["case_id"], ctx.body.recommendationId, ctx.body.summary,
         ctx.body.traceId),
    )
    return {
        "attachmentId": row["attachment_id"],
        "caseId": row["case_id"],
        "type": row["attachment_type"],
        "createdAt": iso(row["created_at"]),
    }


@HANDLERS.operation("getCaseStatus", nullable=("assignedTeamId", "auditTraceId"))
async def case_status(ctx: RequestContext) -> dict[str, Any]:
    row = await load(ctx, ctx.path["case_id"])
    return {
        "caseId": row["case_id"],
        "status": row["status"],
        "assignedTeamId": row["assigned_team_id"],
        "workflowState": workflow_state(row),
        "auditTraceId": row["audit_trace_id"],
    }
